from __future__ import annotations

from typing import Any


AGENT_KEY = "traffic_forecast"
AGENT_NAME = "Traffic Forecast Agent"
LLM_PROMPT = (
    "Review the post-shaping peak RPS and required pod count against current RPS, pods, "
    "and HPA desired replicas. Return JSON exactly like "
    '{"peak_rps_assessment": "...", "pod_recommendation": "...", "risk": "..."}.'
)


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    policy = context["policy"]
    signals = context.get("signals", {})
    traffic = context.get("traffic", {})
    shaping = context["agent_results"]["demand_shaping"]
    before = traffic.get("prometheus_rps", signals.get("baseline_peak_rps", 1420))
    window = shaping.get("send_window_minutes", policy["max_general_delay_minutes"])
    reduction = shaping.get("peak_reduction_percent", min(60, max(10, int(window * 4.2))))
    after = max(1, int(before * (100 - reduction) / 100))
    pods = traffic.get("hpa_desired_replicas", signals.get("required_app_pods", 29))
    live = context.get("live", {}).get("commands", {})
    live_enabled = any(command.get("status") == "ok" for command in live.values())
    result = {
        "peak_rps_before": before,
        "peak_rps_after": after,
        "required_app_pods": pods,
        "based_on": "demand_shaping",
        "send_window_minutes": window,
        "peak_reduction_percent": reduction,
        "vip_send_mode": shaping.get("vip_send_mode"),
        "general_send_mode": shaping.get("general_send_mode"),
        "alb_request_count_5m": traffic.get("alb_request_count_5m"),
        "p95_latency_ms": traffic.get("p95_latency_ms"),
        "queue_depth": traffic.get("queue_depth"),
        "hpa_current_replicas": traffic.get("hpa_current_replicas"),
        "hpa_current_cpu_utilization_percent": traffic.get("hpa_current_cpu_utilization_percent"),
        "source": "kubectl" if live_enabled else "traffic_observability_signal",
    }
    return result, f"Forecast peak RPS changes from {before} to {after}; prepare {pods} app pods."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    result["peak_rps_assessment"] = assessment.get("peak_rps_assessment")
    result["pod_recommendation"] = assessment.get("pod_recommendation")
    result["risk"] = assessment.get("risk")
    return result
