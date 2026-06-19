from __future__ import annotations

from typing import Any


AGENT_SEQUENCE = [
    ("business_control", "Business Control Agent"),
    ("demand_shaping", "Demand Shaping Agent"),
    ("traffic_forecast", "Traffic Forecast Agent"),
    ("bottleneck_capacity", "Bottleneck Capacity Agent"),
    ("infra_execution", "Infra Execution Planner"),
    ("cost", "Cost Agent"),
    ("unit_economics", "Unit Economics Agent"),
    ("policy_guardrail", "Policy Guardrail Agent"),
    ("observer", "Observer Agent"),
    ("fallback", "Fallback Planner"),
    ("postmortem_learning", "Postmortem Learning Agent"),
]

AGENT_TASK_QUEUES = {
    "business_control": "finops-business-control-agent-task-queue",
    "demand_shaping": "finops-demand-shaping-agent-task-queue",
    "traffic_forecast": "finops-traffic-forecast-agent-task-queue",
    "bottleneck_capacity": "finops-bottleneck-capacity-agent-task-queue",
    "cost": "finops-cost-agent-task-queue",
    "policy_guardrail": "finops-policy-guardrail-agent-task-queue",
}

AGENT_DATA_REQUESTS = {
    "demand_shaping": [
        {
            "source_key": "business_control",
            "source_name": "Business Control Agent",
            "field": "max_delay_minutes",
            "label": "일반 사용자 허용 지연 시간",
            "reason": "푸시 분산 구간을 정하려면 정책상 허용 지연 시간이 필요합니다.",
        },
    ],
    "traffic_forecast": [
        {
            "source_key": "demand_shaping",
            "source_name": "Demand Shaping Agent",
            "field": "peak_reduction_percent",
            "label": "분산 발송 후 예상 peak 감소율",
            "reason": "평탄화 후 RPS를 다시 계산하기 위한 보정값입니다.",
        },
        {
            "source_key": "business_control",
            "source_name": "Business Control Agent",
            "field": "target_users",
            "label": "대상 사용자 수",
            "reason": "푸시 대상 규모를 기준으로 원래 peak를 추정합니다.",
        },
    ],
    "bottleneck_capacity": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "peak_rps_after",
            "label": "병목 검증 기준 RPS",
            "reason": "DB/cache/LB가 감당해야 할 트래픽 기준입니다.",
        },
    ],
    "infra_execution": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "required_app_pods",
            "label": "준비해야 할 app pod 수",
            "reason": "scale-out 목표치를 계산하는 기준입니다.",
        },
    ],
    "cost": [
        {
            "source_key": "infra_execution",
            "source_name": "Infra Execution Planner",
            "field": "target_app_pods",
            "label": "비용 계산 기준 pod 수",
            "reason": "EKS/EC2 비용 산정에 사용할 목표 pod 수입니다.",
        },
    ],
    "unit_economics": [
        {
            "source_key": "cost",
            "source_name": "Cost Agent",
            "field": "total",
            "label": "예상 총 비용",
            "reason": "비즈니스 가치 대비 비용 비율을 계산합니다.",
        },
    ],
    "policy_guardrail": [
        {
            "source_key": "unit_economics",
            "source_name": "Unit Economics Agent",
            "field": "cost_ratio",
            "label": "비용 대비 가치 비율",
            "reason": "정책상 승인 또는 차단 여부를 판단합니다.",
        },
    ],
    "observer": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "peak_rps_after",
            "label": "관측 기준 예상 RPS",
            "reason": "실행 중 실제 RPS와 비교할 기준값입니다.",
        },
        {
            "source_key": "policy_guardrail",
            "source_name": "Policy Guardrail Agent",
            "field": "approval_required",
            "label": "실행 전 승인 필요 여부",
            "reason": "승인 전에는 실제 실행 액션을 보류해야 합니다.",
        },
    ],
    "fallback": [
        {
            "source_key": "policy_guardrail",
            "source_name": "Policy Guardrail Agent",
            "field": "allowed",
            "label": "정책상 허용된 실행 액션",
            "reason": "허용되지 않은 액션을 fallback에서 제외합니다.",
        },
    ],
    "postmortem_learning": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "peak_rps_before",
            "label": "사후 비교용 원래 예상 RPS",
            "reason": "예측값과 실제값의 차이를 학습 데이터로 남깁니다.",
        },
        {
            "source_key": "cost",
            "source_name": "Cost Agent",
            "field": "total",
            "label": "사후 비교용 예상 비용",
            "reason": "예상 비용과 실제 비용을 비교합니다.",
        },
    ],
}


AGENT_CONFIDENCE = {
    "business_control": 0.91,
    "demand_shaping": 0.86,
    "traffic_forecast": 0.82,
    "bottleneck_capacity": 0.78,
    "infra_execution": 0.84,
    "cost": 0.8,
    "unit_economics": 0.79,
    "policy_guardrail": 0.9,
    "observer": 0.76,
    "fallback": 0.88,
    "postmortem_learning": 0.74,
}


def get_agent_data_requests(agent_key: str, available_results: dict[str, Any]) -> list[dict[str, Any]]:
    requests = []
    for request in AGENT_DATA_REQUESTS.get(agent_key, []):
        source_result = available_results.get(request["source_key"], {})
        status = "available" if request["field"] in source_result else "requested"
        requests.append({**request, "status": status})
    return requests


def standard_response(
    agent_key: str,
    agent_name: str,
    result: dict[str, Any],
    message: str,
    available_results: dict[str, Any],
) -> dict[str, Any]:
    return {
        "agent": agent_name,
        "agent_key": agent_key,
        "result": result,
        "message": message,
        "data_requests": get_agent_data_requests(agent_key, available_results),
        "confidence": AGENT_CONFIDENCE.get(agent_key, 0.75),
    }


def run_agent(agent_key: str, context: dict[str, Any]) -> dict[str, Any]:
    event = context["event"]
    policy = context["policy"]
    signals = context.get("signals", {})
    business = context.get("business", {})
    traffic = context.get("traffic", {})
    infra = context.get("infra", {})
    cost_source = context.get("cost_source", {})
    policy_source = context.get("policy_source", {})
    live = context.get("live", {})
    live_commands = live.get("commands", {})
    live_enabled = any(result.get("status") == "ok" for result in live_commands.values())
    previous = context.get("agent_results", {})
    agent_name = dict(AGENT_SEQUENCE).get(agent_key, agent_key)

    if agent_key == "business_control":
        result = {
            "event_id": event["event_id"],
            "grade": event["grade"],
            "target_users": event["target_users"],
            "vip_audience_count": business.get("vip_audience_count"),
            "general_audience_count": business.get("general_audience_count"),
            "push_channel": business.get("push_channel"),
            "campaign_importance": business.get("campaign_importance"),
            "approval_required": policy["approval_required"],
            "max_delay_minutes": policy["max_general_delay_minutes"],
            "source": business.get("calendar_source", "business_calendar"),
        }
        message = (
            f"{event['title']} 일정은 {event['grade']}등급 이벤트입니다. "
            f"대상자는 {event['target_users']:,}명이고 일반 사용자는 최대 "
            f"{policy['max_general_delay_minutes']}분까지 지연할 수 있습니다."
        )
    elif agent_key == "demand_shaping":
        delay = policy["max_general_delay_minutes"]
        result = {
            "vip": "immediate" if policy["vip_immediate"] else "batched",
            "general_users": f"spread_over_{delay}m",
            "peak_reduction_percent": 42,
            "vip_audience_count": business.get("vip_audience_count"),
            "general_audience_count": business.get("general_audience_count"),
            "crm_segment": business.get("crm_segment"),
        }
        message = (
            f"Business Control 결과를 받아 VIP는 즉시 발송하고 일반 사용자는 {delay}분 동안 분산하겠습니다. "
            "이 전략이면 예상 peak를 약 42% 낮출 수 있습니다."
        )
    elif agent_key == "traffic_forecast":
        shaping = previous["demand_shaping"]
        before = traffic.get("prometheus_rps", signals.get("baseline_peak_rps", 1420))
        after = signals.get("shaped_peak_rps", 820 if shaping["peak_reduction_percent"] >= 40 else 980)
        pods = traffic.get("hpa_desired_replicas", signals.get("required_app_pods", 29))
        result = {
            "peak_rps_before": before,
            "peak_rps_after": after,
            "required_app_pods": pods,
            "based_on": "demand_shaping",
            "alb_request_count_5m": traffic.get("alb_request_count_5m"),
            "p95_latency_ms": traffic.get("p95_latency_ms"),
            "queue_depth": traffic.get("queue_depth"),
            "hpa_current_replicas": traffic.get("hpa_current_replicas"),
            "hpa_current_cpu_utilization_percent": traffic.get("hpa_current_cpu_utilization_percent"),
            "source": "kubectl" if live_enabled else "traffic_observability_signal",
        }
        message = (
            f"Demand Shaping 결과를 반영하면 peak는 {before} rps에서 {after} rps로 낮아집니다. "
            f"이 수준에서는 app pod {pods}개를 준비하는 계획이 적절합니다."
        )
    elif agent_key == "bottleneck_capacity":
        forecast = previous["traffic_forecast"]
        db_cpu = infra.get("rds_cpu_percent", signals.get("db_cpu_percent", 68))
        cache_hit_ratio = infra.get("redis_cache_hit_ratio_percent", signals.get("cache_hit_ratio_percent", 91))
        result = {
            "db_cpu": f"{db_cpu}%",
            "rds_connections": infra.get("rds_connections"),
            "rds_read_iops": infra.get("rds_read_iops"),
            "cache_hit_ratio": f"{cache_hit_ratio}%",
            "alb_status": signals.get("alb_status", "ok"),
            "alb_healthy_targets": infra.get("alb_healthy_targets"),
            "alb_unhealthy_targets": infra.get("alb_unhealthy_targets"),
            "ready_pods": infra.get("ready_pods"),
            "running_pods": infra.get("running_pods"),
            "source": "kubectl+infra_capacity_signal" if live_enabled else "infra_capacity_signal",
            "status": "warning" if db_cpu >= 65 or cache_hit_ratio < 93 else "ok",
            "validated_rps": forecast["peak_rps_after"],
        }
        message = (
            f"{forecast['peak_rps_after']} rps 기준으로 DB CPU는 {db_cpu}%, cache hit ratio는 {cache_hit_ratio}%로 예상됩니다. "
            "전체 경로는 버틸 수 있지만 cache hit ratio는 계속 관찰해야 합니다."
        )
    elif agent_key == "infra_execution":
        forecast = previous["traffic_forecast"]
        result = {
            "scale_out_at": "T-20m",
            "prewarm_at": "T-15m",
            "scale_down": "observed_rps_based",
            "target_app_pods": forecast["required_app_pods"],
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
        message = (
            f"T-20분에 app pod를 {forecast['required_app_pods']}개까지 준비하고 "
            "T-15분에 CDN/cache pre-warm을 시작하겠습니다."
        )
    elif agent_key == "cost":
        infra = previous["infra_execution"]
        eks = float(signals.get("eks_cost_usd", 31.2))
        network = float(signals.get("network_cost_usd", 8.1))
        logs = float(signals.get("log_cost_usd", 3.4))
        push = float(signals.get("push_cost_usd", 7.6))
        daily_namespace = float(cost_source.get("kubecost_namespace_daily_usd", 0))
        event_budget = float(cost_source.get("event_incremental_budget_usd", eks + network + logs + push))
        total = round(min(eks + network + logs + push, event_budget), 2)
        result = {
            "eks": eks,
            "network": network,
            "logs": logs,
            "push": push,
            "total": total,
            "pod_count": infra["target_app_pods"],
            "cost_explorer_month_to_date_usd": cost_source.get("cost_explorer_month_to_date_usd"),
            "cur_projected_monthly_usd": cost_source.get("cur_projected_monthly_usd"),
            "kubecost_namespace_daily_usd": daily_namespace,
            "event_incremental_budget_usd": event_budget,
            "source": (
                "aws_cost_explorer+cost_signal"
                if cost_source.get("cost_explorer_source") == "aws_cost_explorer"
                else "cost_signal"
            ),
        }
        message = (
            f"{infra['target_app_pods']}개 pod 준비안을 기준으로 총 비용은 약 ${total}입니다. "
            "가장 큰 비용 항목은 EKS/EC2 용량 비용입니다."
        )
    elif agent_key == "unit_economics":
        cost = previous["cost"]
        expected_value = float(signals.get("expected_value_usd", 4200))
        cost_ratio = round((cost["total"] / expected_value) * 100, 1) if expected_value else 100.0
        result = {
            "expected_value_usd": expected_value,
            "cost_ratio": f"{cost_ratio}%",
            "override": cost_ratio > 5,
            "estimated_cost_usd": cost["total"],
        }
        message = (
            f"예상 비즈니스 가치는 약 ${expected_value:g}이고 비용 비율은 {cost_ratio}%입니다. "
            "비용 대비 실행 가치는 충분하다고 판단합니다."
        )
    elif agent_key == "policy_guardrail":
        unit = previous["unit_economics"]
        result = {
            "allowed": policy_source.get("allowed_actions", ["scale_out", "prewarm", "spread_push"]),
            "forbidden": policy_source.get("forbidden_actions", []),
            "approval_required": policy["approval_required"],
            "cost_ratio": unit["cost_ratio"],
            "monthly_budget_limit_usd": policy_source.get("monthly_budget_limit_usd"),
            "approval_required_over_usd": policy_source.get("approval_required_over_usd"),
            "policy_version": policy_source.get("policy_version"),
        }
        message = (
            "정책상 scale-out, pre-warm, push 분산은 허용됩니다. "
            "다만 S등급 이벤트이므로 운영자 승인이 필요합니다."
        )
    elif agent_key == "observer":
        threshold = signals.get("scale_down_rps_threshold", 600)
        result = {
            "mode": "armed",
            "watch": ["rps", "latency", "db_cpu", "cost_burn"],
            "recommendation": f"scale_down_if_actual_rps_below_{threshold}",
        }
        message = (
            "실행 중에는 RPS, latency, DB CPU, 비용 burn rate를 관찰하겠습니다. "
            f"실제 RPS가 {threshold} 미만이면 단계적 scale-down을 권고합니다."
        )
    elif agent_key == "fallback":
        result = {"vip_only": True, "general_hold": True, "static_report": True}
        message = (
            "문제가 생기면 VIP만 우선 발송하고 일반 사용자는 hold합니다. "
            "필요하면 static report로 대체 경로를 제공합니다."
        )
    elif agent_key == "postmortem_learning":
        result = {"profile_update": "pending_after_execution", "compare": ["forecast", "actual", "cost"]}
        message = (
            "이벤트 종료 후 예측값, 실제 트래픽, 실제 비용을 비교해서 "
            "다음 이벤트 profile을 갱신하겠습니다."
        )
    else:
        raise ValueError(f"unknown agent: {agent_key}")

    return standard_response(agent_key, agent_name, result, message, previous)


def build_final_plan(context: dict[str, Any]) -> dict[str, Any]:
    forecast = context["agent_results"]["traffic_forecast"]
    cost = context["agent_results"]["cost"]
    policy = context["agent_results"]["policy_guardrail"]
    infra = context["agent_results"].get("infra_execution", {})
    bottleneck = context["agent_results"].get("bottleneck_capacity", {})
    observer = context["agent_results"].get("observer", {})
    fallback = context["agent_results"].get("fallback", {})
    postmortem = context["agent_results"].get("postmortem_learning", {})
    data_sources = {
        "business": context.get("business", {}).get("calendar_source", "business_calendar"),
        "traffic": forecast.get("source", "traffic_observability_signal"),
        "infra": infra.get("source", "infra_capacity_signal"),
        "cost": cost.get("source", "cost_signal"),
        "policy": context.get("policy_source", {}).get("policy_version", "business_policy"),
    }
    return {
        "event_id": context["event"]["event_id"],
        "peak_rps_before": forecast["peak_rps_before"],
        "peak_rps_after": forecast["peak_rps_after"],
        "required_app_pods": forecast["required_app_pods"],
        "estimated_cost_usd": cost["total"],
        "approval_required": policy["approval_required"],
        "execution_mode": "dry_run",
        "data_sources": data_sources,
        "report": {
            "title": "FinOps Event Readiness Report",
            "event": {
                "event_id": context["event"]["event_id"],
                "title": context["event"]["title"],
                "grade": context["event"]["grade"],
                "target_users": context["event"]["target_users"],
                "scheduled_at": context["event"]["scheduled_at"],
            },
            "executive_summary": (
                f"Peak RPS is expected to move from {forecast['peak_rps_before']} to "
                f"{forecast['peak_rps_after']} after demand shaping. Prepare "
                f"{forecast['required_app_pods']} app pods with dry-run execution mode. "
                f"Estimated incremental event cost is ${cost['total']}."
            ),
            "data_collection": {
                "sources": data_sources,
                "live_command_success_count": "see agent decision payloads",
                "failed_collectors": "see agent decision payloads",
            },
            "traffic": {
                "peak_rps_before": forecast["peak_rps_before"],
                "peak_rps_after": forecast["peak_rps_after"],
                "required_app_pods": forecast["required_app_pods"],
                "queue_depth": forecast.get("queue_depth"),
                "p95_latency_ms": forecast.get("p95_latency_ms"),
            },
            "capacity": {
                "target_app_pods": infra.get("target_app_pods"),
                "current_app_pods": infra.get("current_app_pods"),
                "ready_app_pods": infra.get("ready_app_pods"),
                "bottleneck_status": bottleneck.get("status"),
                "rds_cpu": bottleneck.get("db_cpu"),
                "cache_hit_ratio": bottleneck.get("cache_hit_ratio"),
                "spot_candidates": infra.get("spot_instance_types", []),
                "spot_placement_scores": infra.get("spot_placement_scores", []),
            },
            "cost": {
                "estimated_event_cost_usd": cost["total"],
                "month_to_date_usd": cost.get("cost_explorer_month_to_date_usd"),
                "projected_monthly_usd": cost.get("cur_projected_monthly_usd"),
                "event_budget_usd": cost.get("event_incremental_budget_usd"),
            },
            "policy": {
                "approval_required": policy["approval_required"],
                "allowed_actions": policy.get("allowed", []),
                "forbidden_actions": policy.get("forbidden", []),
                "policy_version": policy.get("policy_version"),
            },
            "operations": {
                "scale_out_at": infra.get("scale_out_at"),
                "prewarm_at": infra.get("prewarm_at"),
                "scale_down": infra.get("scale_down"),
                "observer_recommendation": observer.get("recommendation"),
                "fallback": fallback,
                "postmortem": postmortem,
            },
        },
        "recommended_actions": [
            "VIP 사용자는 즉시 발송",
            f"일반 사용자는 {context['policy']['max_general_delay_minutes']}분 동안 분산 발송",
            "런칭 15분 전 CDN/cache pre-warm",
            "예상 peak에 맞춰 app pod scale-out 후 실제 RPS 기반 scale-down",
        ],
    }
