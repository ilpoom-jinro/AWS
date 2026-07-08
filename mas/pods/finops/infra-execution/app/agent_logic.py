from __future__ import annotations

import math
import os
from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "infra_execution"
AGENT_NAME = "Infra Capacity Planning Agent"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    infra = context.get("infra", {})
    policy = context.get("policy", {})
    event = context.get("event", {})
    forecast = get_agent_result(context, "traffic_forecast")
    cluster_state = _optional_agent_result(context, "cluster_state")
    bottleneck = _optional_agent_result(context, "bottleneck_capacity")
    business_control = _optional_agent_result(context, "business_control")

    live = context.get("live", {}).get("commands", {})
    live_enabled = any(command.get("status") == "ok" for command in live.values())
    current_pods = _current_pods(forecast, cluster_state, infra)
    target = int(forecast["required_app_pods"])
    scale_out_pods = max(0, target - current_pods)
    grade = event.get("grade") or business_control.get("grade") or "A"
    nodegroup_desired = int(infra.get("nodegroup_desired") or 0)
    nodegroup_max = int(infra.get("nodegroup_max") or 30)
    pods_per_node = int(os.getenv("PODS_PER_NODE_FOR_PLANNING", "8"))

    candidate_capacity_plans = [
        _build_candidate_capacity_plan(
            candidate,
            current_pods=current_pods,
            grade=grade,
            nodegroup_desired=nodegroup_desired,
            nodegroup_max=nodegroup_max,
            pods_per_node=pods_per_node,
        )
        for candidate in forecast.get("candidate_forecasts", [])
    ]
    if not candidate_capacity_plans:
        candidate_capacity_plans = [
            _build_candidate_capacity_plan(
                {
                    "label": "기본 계획",
                    "required_app_pods": target,
                    "scale_out_pods": scale_out_pods,
                    "estimated_p95_ms": forecast.get("estimated_p95_ms", forecast.get("p95_latency_ms")),
                    "peak_rps_after": forecast.get("peak_rps_after"),
                    "send_window_minutes": forecast.get("send_window_minutes"),
                },
                current_pods=current_pods,
                grade=grade,
                nodegroup_desired=nodegroup_desired,
                nodegroup_max=nodegroup_max,
                pods_per_node=pods_per_node,
            )
        ]

    selected_plan = candidate_capacity_plans[0]
    idle_resource_plan = _build_idle_resource_plan(cluster_state)
    total_idle_saving = round(
        sum(float(item.get("estimated_saving_usd", 0) or 0) for item in idle_resource_plan),
        2,
    )
    nodegroup_capacity_check = _nodegroup_capacity_check(
        additional_pods=scale_out_pods,
        nodegroup_desired=nodegroup_desired,
        nodegroup_max=nodegroup_max,
        pods_per_node=pods_per_node,
    )
    approval_required_actions = ["scale_out_app_pods"]
    if idle_resource_plan:
        approval_required_actions.append("reduce_idle_resources")
    if nodegroup_capacity_check["max_adjustment_required"]:
        approval_required_actions.append("adjust_nodegroup_max")

    spot_allowed_for_scale_target = grade != "S"
    cost_optimization_hints = [
        "Use existing nodegroup headroom before increasing nodegroup max.",
        "Scale only the traffic-serving target deployment, not the full namespace.",
        "Review idle non-event workloads for temporary reduction with operator approval.",
    ]
    if not spot_allowed_for_scale_target:
        cost_optimization_hints.append(
            "Grade S event: do not use Spot for critical scale-target capacity."
        )

    result = {
        "scale_out_at": selected_plan["scale_out_at"],
        "prewarm_at": selected_plan["prewarm_at"],
        "scale_down": "observed_rps_based",
        "target_app_pods": target,
        "current_app_pods": current_pods,
        "scale_out_pods": scale_out_pods,
        "ready_app_pods": bottleneck.get("ready_pods", infra.get("ready_pods")),
        "deployment_ready_replicas": infra.get("deployment_ready_replicas"),
        "nodegroup_desired": nodegroup_desired,
        "nodegroup_max": nodegroup_max,
        "nodegroup_capacity_check": nodegroup_capacity_check,
        "capacity_plan": {
            "current_pods": current_pods,
            "target_pods": target,
            "additional_pods": scale_out_pods,
            "reason": f"{selected_plan['label']}_requires_{target}_pods",
            "scale_out_at": selected_plan["scale_out_at"],
            "prewarm_at": selected_plan["prewarm_at"],
        },
        "candidate_capacity_plans": candidate_capacity_plans,
        "idle_resource_plan": idle_resource_plan,
        "idle_resource_saving_usd": total_idle_saving,
        "approval_required_actions": approval_required_actions,
        "cost_optimization_hints": cost_optimization_hints,
        "spot_policy": {
            "scale_target_capacity_type": "on_demand",
            "spot_allowed_for_scale_target": spot_allowed_for_scale_target,
            "reason": (
                "Grade S event requires stable on-demand capacity"
                if not spot_allowed_for_scale_target
                else "Lower-grade event may evaluate non-critical Spot capacity"
            ),
        },
        "spot_instance_types": infra.get("spot_instance_types", []),
        "latest_spot_prices": infra.get("latest_spot_prices", []),
        "spot_placement_scores": infra.get("spot_placement_scores", []),
        "instance_type_offering_count": infra.get("instance_type_offering_count"),
        "eks_nodegroup_capacity_type": infra.get("eks_nodegroup_capacity_type"),
        "eks_nodegroup_status": infra.get("eks_nodegroup_status"),
        "source": "kubectl+infra_capacity_signal" if live_enabled else "infra_capacity_signal",
        "evidence": [
            f"Traffic Forecast required_app_pods={target}를 사용했습니다.",
            f"현재 app pod 수는 {current_pods}개입니다.",
            f"추가 증설 pod 수는 {scale_out_pods}개입니다.",
            f"Scale-out 시점은 {selected_plan['scale_out_at']}입니다.",
            f"Prewarm 시점은 {selected_plan['prewarm_at']}입니다.",
            f"Nodegroup desired={nodegroup_desired}, max={nodegroup_max}입니다.",
            f"유휴 자원 절감 후보는 {len(idle_resource_plan)}개입니다.",
        ],
    }

    historical_avg_pods = business_control.get("historical_avg_pods")
    if historical_avg_pods and target:
        pod_variance = (target - historical_avg_pods) / historical_avg_pods
        result["historical_avg_pods"] = historical_avg_pods
        result["pod_variance_from_history"] = round(pod_variance * 100, 1)
        if pod_variance > 0.3:
            result.setdefault("warnings", []).append(
                f"Required pods({target}) are {pod_variance * 100:+.0f}% above "
                f"historical average({historical_avg_pods}); review capacity plan."
            )
    if nodegroup_capacity_check["max_adjustment_required"]:
        result.setdefault("warnings", []).append(
            "Nodegroup max may be insufficient for the selected scale-out plan."
        )

    return (
        result,
        (
            f"Plan capacity from {current_pods} to {target} pods "
            f"({scale_out_pods:+d}) at {selected_plan['scale_out_at']}; "
            f"prewarm at {selected_plan['prewarm_at']}."
        ),
    )


def _optional_agent_result(context: dict[str, Any], agent_key: str) -> dict[str, Any]:
    try:
        return get_agent_result(context, agent_key)
    except KeyError:
        return {}


def _current_pods(
    forecast: dict[str, Any],
    cluster_state: dict[str, Any],
    infra: dict[str, Any],
) -> int:
    return int(
        forecast.get("current_pods")
        or cluster_state.get("scale_target_current_pods")
        or infra.get("eks_deployment_replicas")
        or infra.get("ready_pods")
        or 0
    )


def _build_candidate_capacity_plan(
    candidate: dict[str, Any],
    *,
    current_pods: int,
    grade: str,
    nodegroup_desired: int,
    nodegroup_max: int,
    pods_per_node: int,
) -> dict[str, Any]:
    target_pods = int(candidate.get("required_app_pods") or 1)
    additional_pods = max(0, int(candidate.get("scale_out_pods", target_pods - current_pods)))
    additional_nodes_required = math.ceil(additional_pods / max(pods_per_node, 1))
    timing = _timing(additional_pods=additional_pods, additional_nodes_required=additional_nodes_required)
    max_adjustment_required = nodegroup_desired + additional_nodes_required > nodegroup_max
    return {
        "label": candidate.get("label", "기본 계획"),
        "current_app_pods": current_pods,
        "required_app_pods": target_pods,
        "target_app_pods": target_pods,
        "scale_out_pods": additional_pods,
        "estimated_p95_ms": candidate.get("estimated_p95_ms"),
        "peak_rps_after": candidate.get("peak_rps_after"),
        "send_window_minutes": candidate.get("send_window_minutes") or candidate.get("push_window_minutes"),
        "scale_out_at": timing["scale_out_at"],
        "prewarm_at": timing["prewarm_at"],
        "additional_nodes_required": additional_nodes_required,
        "nodegroup_max_adjustment_required": max_adjustment_required,
        "scale_target_capacity_type": "on_demand",
        "spot_excluded_for_scale_target": grade == "S",
        "spot_policy_reason": (
            "Grade S event keeps critical traffic capacity on on-demand nodes"
            if grade == "S"
            else "Spot may be evaluated only for non-critical helper workloads"
        ),
    }


def _timing(*, additional_pods: int, additional_nodes_required: int) -> dict[str, Any]:
    pod_ready_seconds = int(os.getenv("POD_READY_SECONDS", "90"))
    image_pull_seconds = int(os.getenv("IMAGE_PULL_SECONDS", "120"))
    hpa_stabilization_seconds = int(os.getenv("HPA_STABILIZATION_SECONDS", "120"))
    node_bootstrap_seconds = int(os.getenv("NODE_BOOTSTRAP_SECONDS", "480"))
    cache_warmup_seconds = int(os.getenv("CACHE_WARMUP_SECONDS", "300"))
    safety_buffer_seconds = int(os.getenv("SCALE_SAFETY_BUFFER_SECONDS", "300"))
    total_seconds = (
        pod_ready_seconds
        + image_pull_seconds
        + hpa_stabilization_seconds
        + cache_warmup_seconds
        + safety_buffer_seconds
    )
    if additional_nodes_required > 0:
        total_seconds += node_bootstrap_seconds
    if additional_pods <= 0:
        total_seconds = cache_warmup_seconds + safety_buffer_seconds
    scale_out_minutes = max(5, math.ceil(total_seconds / 60))
    prewarm_minutes = max(15, math.ceil((cache_warmup_seconds + safety_buffer_seconds) / 60))
    return {
        "scale_out_at": f"T-{scale_out_minutes}m",
        "prewarm_at": f"T-{prewarm_minutes}m",
        "scale_out_lead_minutes": scale_out_minutes,
        "prewarm_lead_minutes": prewarm_minutes,
    }


def _build_idle_resource_plan(cluster_state: dict[str, Any]) -> list[dict[str, Any]]:
    plans = []
    for item in cluster_state.get("idle_candidates", []) or []:
        current = int(item.get("current_replicas") or 0)
        reducible = int(item.get("reducible_replicas") or 0)
        if reducible <= 0:
            continue
        plans.append(
            {
                "namespace": item.get("namespace"),
                "deployment": item.get("deployment"),
                "current_replicas": current,
                "target_replicas": max(0, current - reducible),
                "reducible_replicas": reducible,
                "estimated_saving_usd": float(item.get("estimated_saving_usd") or 0),
                "risk": item.get("risk", "medium"),
                "requires_approval": True,
                "action": "propose_scale_down_idle_resource",
            }
        )
    return plans


def _nodegroup_capacity_check(
    *,
    additional_pods: int,
    nodegroup_desired: int,
    nodegroup_max: int,
    pods_per_node: int,
) -> dict[str, Any]:
    additional_nodes_required = math.ceil(additional_pods / max(pods_per_node, 1))
    projected_nodes = nodegroup_desired + additional_nodes_required
    return {
        "pods_per_node_assumption": pods_per_node,
        "additional_nodes_required": additional_nodes_required,
        "nodegroup_desired": nodegroup_desired,
        "nodegroup_max": nodegroup_max,
        "projected_node_count": projected_nodes,
        "max_adjustment_required": projected_nodes > nodegroup_max,
        "remaining_node_headroom": max(0, nodegroup_max - nodegroup_desired),
    }


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
