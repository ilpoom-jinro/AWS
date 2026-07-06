from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "infra_execution"
AGENT_NAME = "Infra Execution Planner"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    infra = context.get("infra", {})
    forecast = get_agent_result(context, "traffic_forecast")
    live = context.get("live", {}).get("commands", {})
    live_enabled = any(command.get("status") == "ok" for command in live.values())
    target = forecast["required_app_pods"]
    result = {
        "scale_out_at": "T-20m",
        "prewarm_at": "T-15m",
        "scale_down": "observed_rps_based",
        "target_app_pods": target,
        "current_app_pods": infra.get("eks_deployment_replicas"),
        "ready_app_pods": infra.get("ready_pods"),
        "deployment_ready_replicas": infra.get("deployment_ready_replicas"),
        "nodegroup_desired": infra.get("nodegroup_desired"),
        "nodegroup_max": infra.get("nodegroup_max"),
        "spot_instance_types": infra.get("spot_instance_types", []),
        "latest_spot_prices": infra.get("latest_spot_prices", []),
        "spot_placement_scores": infra.get("spot_placement_scores", []),
        "instance_type_offering_count": infra.get("instance_type_offering_count"),
        "eks_nodegroup_capacity_type": infra.get("eks_nodegroup_capacity_type"),
        "eks_nodegroup_status": infra.get("eks_nodegroup_status"),
        "source": "kubectl+infra_capacity_signal" if live_enabled else "infra_capacity_signal",
    }
    try:
        business_control = get_agent_result(context, "business_control")
    except KeyError:
        business_control = {}
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
    return result, f"Plan a dry-run scale-out to {target} pods at T-20m and prewarm at T-15m."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
