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
    key: f"finops-{key.replace('_', '-')}-agent-task-queue"
    for key, _ in AGENT_SEQUENCE
}


def _request(
    source_key: str,
    field: str,
    label: str,
    reason: str,
) -> dict[str, str]:
    return {
        "source_key": source_key,
        "source_name": dict(AGENT_SEQUENCE)[source_key],
        "field": field,
        "label": label,
        "reason": reason,
    }


AGENT_DATA_REQUESTS = {
    "demand_shaping": [
        _request("business_control", "max_delay_minutes", "allowed delay", "Build the send window."),
    ],
    "traffic_forecast": [
        _request("demand_shaping", "peak_reduction_percent", "peak reduction", "Forecast shaped RPS."),
        _request("business_control", "target_users", "target audience", "Size the event demand."),
    ],
    "bottleneck_capacity": [
        _request("traffic_forecast", "peak_rps_after", "forecast RPS", "Validate downstream capacity."),
    ],
    "infra_execution": [
        _request("traffic_forecast", "required_app_pods", "required pods", "Create the scale plan."),
    ],
    "cost": [
        _request("infra_execution", "target_app_pods", "target pods", "Estimate incremental cost."),
    ],
    "unit_economics": [
        _request("cost", "total", "estimated cost", "Compare cost with expected value."),
    ],
    "policy_guardrail": [
        _request("unit_economics", "cost_ratio", "cost-to-value ratio", "Validate policy and approval."),
    ],
    "observer": [
        _request("traffic_forecast", "peak_rps_after", "forecast RPS", "Set monitoring thresholds."),
        _request("policy_guardrail", "approval_required", "approval requirement", "Gate operations."),
    ],
    "fallback": [
        _request("policy_guardrail", "allowed", "allowed actions", "Exclude prohibited fallback actions."),
    ],
    "postmortem_learning": [
        _request("traffic_forecast", "peak_rps_before", "forecast baseline", "Compare forecast and actual."),
        _request("cost", "total", "forecast cost", "Compare estimated and actual cost."),
    ],
}


def build_final_plan(context: dict[str, Any]) -> dict[str, Any]:
    results = context["agent_results"]
    forecast = results["traffic_forecast"]
    cost = results["cost"]
    policy = results["policy_guardrail"]
    infra = results.get("infra_execution", {})
    bottleneck = results.get("bottleneck_capacity", {})
    observer = results.get("observer", {})
    fallback = results.get("fallback", {})
    postmortem = results.get("postmortem_learning", {})
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
                f"{forecast['required_app_pods']} app pods in dry-run mode. "
                f"Estimated incremental cost is ${cost['total']}."
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
                "cur_month_to_date_usd": cost.get("cur_month_to_date_usd"),
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
            "Send VIP notifications immediately",
            f"Spread general notifications over {context['policy']['max_general_delay_minutes']} minutes",
            "Prewarm CDN and cache 15 minutes before the event",
            "Scale out for forecast peak and scale down from observed RPS",
        ],
    }
