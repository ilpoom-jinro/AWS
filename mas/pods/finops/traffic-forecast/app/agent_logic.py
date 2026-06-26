from __future__ import annotations

import math
from typing import Any

from app.agent_support import get_agent_result


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
    shaping = get_agent_result(context, "demand_shaping")
    parameters = context.get("parameters", {})
    broker_data = context.get("broker_results", {}).get("traffic_forecast", {})
    before = traffic.get("prometheus_rps", signals.get("baseline_peak_rps", 1420))
    parameter_window = parameters.get("push_window_minutes")
    broker_window = broker_data.get("push_window_minutes")
    window = (
        parameter_window
        or broker_window
        or shaping.get("send_window_minutes")
        or policy["max_general_delay_minutes"]
    )
    reforecast = parameter_window is not None or broker_window is not None
    reduction = (
        min(60, max(10, int(window * 4.2)))
        if reforecast
        else shaping.get(
            "peak_reduction_percent",
            min(60, max(10, int(window * 4.2))),
        )
    )
    after = max(1, int(before * (100 - reduction) / 100))
    pods = traffic.get("hpa_desired_replicas", signals.get("required_app_pods", 29))
    base_p95 = float(traffic.get("p95_latency_ms") or 0.0)
    estimated_p95 = base_p95
    candidate_forecasts: list[dict[str, Any]] = []
    shaping_candidates = shaping.get("candidates", [])
    if shaping_candidates and not reforecast:
        raw_forecasts = []
        for candidate in shaping_candidates:
            candidate_reduction = candidate["peak_reduction_percent"]
            candidate_peak = max(1, int(before * (100 - candidate_reduction) / 100))
            raw_forecasts.append((candidate, candidate_peak))

        stability_peak = raw_forecasts[0][1]
        for candidate, candidate_peak in raw_forecasts:
            candidate_pods = max(
                1,
                math.ceil(pods * candidate_peak / stability_peak),
            )
            candidate_p95 = round(
                base_p95 * candidate_peak / stability_peak,
                2,
            )
            candidate_forecasts.append(
                {
                    "label": candidate["label"],
                    "push_window_minutes": candidate["push_window_minutes"],
                    "peak_rps_after": candidate_peak,
                    "required_app_pods": candidate_pods,
                    "estimated_p95_ms": candidate_p95,
                }
            )

        first_candidate = shaping_candidates[0]
        first_forecast = candidate_forecasts[0]
        window = first_candidate["push_window_minutes"]
        reduction = first_candidate["peak_reduction_percent"]
        after = first_forecast["peak_rps_after"]
        pods = first_forecast["required_app_pods"]
        estimated_p95 = first_forecast["estimated_p95_ms"]
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
        "reforecast": reforecast,
        "candidate_forecasts": candidate_forecasts,
        "alb_request_count_5m": traffic.get("alb_request_count_5m"),
        "p95_latency_ms": estimated_p95,
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
