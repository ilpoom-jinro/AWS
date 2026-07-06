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
    try:
        business_control = get_agent_result(context, "business_control")
    except KeyError:
        business_control = {}
    parameters = context.get("parameters", {})
    broker_data = context.get("broker_results", {}).get("traffic_forecast", {})
    before = (
        business_control.get("baseline_peak_rps")
        or context.get("baseline_peak_rps")
        or 1400
    )

    constraint_keys = {
        "peak_rps_after",
        "ready_pods",
        "desired_pods",
        "queue_depth",
        "p95_latency_ms",
        "pod_memory_percent",
    }
    operation = parameters.get("operation")
    has_readiness_constraints = bool(constraint_keys.intersection(parameters))
    if operation == "reforecast_with_updated_constraints" or has_readiness_constraints:
        peak_rps_after = int(parameters.get("peak_rps_after", before))
        ready_pods = int(parameters.get("ready_pods", traffic.get("hpa_current_replicas") or 0))
        desired_pods = max(
            1,
            int(
                parameters.get(
                    "desired_pods",
                    traffic.get("hpa_desired_replicas", signals.get("required_app_pods", 29)),
                )
            ),
        )
        queue_depth = int(parameters.get("queue_depth", traffic.get("queue_depth") or 0))
        p95_latency_ms = float(parameters.get("p95_latency_ms", traffic.get("p95_latency_ms") or 0.0))
        pod_memory_percent = float(
            parameters.get(
                "pod_memory_percent",
                traffic.get("pod_memory_percent") or signals.get("pod_memory_percent") or 0.0,
            )
        )

        ready_ratio = ready_pods / desired_pods
        adjusted_capacity_rps = peak_rps_after * ready_ratio
        rps_per_pod = peak_rps_after / desired_pods
        required_app_pods = math.ceil(peak_rps_after / rps_per_pod)

        if queue_depth > 5000:
            risk_level = "high"
        elif queue_depth > 2000:
            risk_level = "medium"
        else:
            risk_level = "low"

        if ready_ratio < 0.7:
            pod_scaling_timeline = "T-25m (추가 준비 시간 필요)"
        else:
            pod_scaling_timeline = "T-20m"

        live = context.get("live", {}).get("commands", {})
        live_enabled = any(command.get("status") == "ok" for command in live.values())
        result = {
            "peak_rps_before": before,
            "peak_rps_after": peak_rps_after,
            "required_app_pods": required_app_pods,
            "based_on": "pod_readiness_constraints",
            "send_window_minutes": shaping.get("send_window_minutes") or policy["max_general_delay_minutes"],
            "peak_reduction_percent": shaping.get("peak_reduction_percent"),
            "vip_send_mode": shaping.get("vip_send_mode"),
            "general_send_mode": shaping.get("general_send_mode"),
            "reforecast": True,
            "reforecast_reason": "pod_readiness_constraint",
            "adjusted_capacity_rps": adjusted_capacity_rps,
            "ready_ratio": ready_ratio,
            "pod_scaling_timeline": pod_scaling_timeline,
            "risk_assessment": {
                "level": risk_level,
                "ready_pods": ready_pods,
                "desired_pods": desired_pods,
                "queue_depth": queue_depth,
                "p95_latency_ms": p95_latency_ms,
            },
            "candidate_forecasts": [],
            "alb_request_count_5m": traffic.get("alb_request_count_5m"),
            "p95_latency_ms": p95_latency_ms,
            "queue_depth": queue_depth,
            "pod_memory_percent": pod_memory_percent,
            "hpa_current_replicas": traffic.get("hpa_current_replicas"),
            "hpa_current_cpu_utilization_percent": traffic.get("hpa_current_cpu_utilization_percent"),
            "source": "kubectl" if live_enabled else "traffic_observability_signal",
            "evidence": [
                f"재예측 기준 peak_rps_after={peak_rps_after}입니다.",
                f"ready_pods={ready_pods}, desired_pods={desired_pods}입니다.",
                f"ready_ratio={ready_pods} / {desired_pods} = {ready_ratio:.3f}입니다.",
                f"adjusted_capacity_rps={peak_rps_after} * {ready_ratio:.3f} = {adjusted_capacity_rps:.2f}입니다.",
                f"queue_depth={queue_depth}, p95_latency_ms={p95_latency_ms}를 확인했습니다.",
                f"pod_scaling_timeline은 {pod_scaling_timeline}입니다.",
            ],
        }
        return (
            result,
            (
                "Reforecast applied with pod readiness constraints; "
                f"ready ratio {ready_ratio:.3f}, adjusted capacity {adjusted_capacity_rps:.2f} RPS."
            ),
        )

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
        "evidence": [
            f"기준 peak RPS는 {before}입니다.",
            f"Demand Shaping 결과 send_window_minutes={window}분을 사용했습니다.",
            f"Demand Shaping 결과 peak_reduction_percent={reduction}%를 사용했습니다.",
            f"계산식: {before} * (100 - {reduction}) / 100 = {after} RPS입니다.",
            f"필요 app pod 수는 {pods}개로 산정했습니다.",
            f"예상 p95 latency는 {estimated_p95}ms입니다.",
            f"데이터 source는 {'kubectl' if live_enabled else 'traffic_observability_signal'}입니다.",
        ],
    }
    historical_avg_shaped_rps = business_control.get("historical_avg_shaped_rps")
    if historical_avg_shaped_rps:
        variance = (after - historical_avg_shaped_rps) / historical_avg_shaped_rps
        result["historical_avg_shaped_rps"] = historical_avg_shaped_rps
        result["forecast_variance_from_history"] = round(variance * 100, 1)
        if abs(variance) > 0.2:
            result.setdefault("warnings", []).append(
                f"Forecast RPS({after}) differs from historical average "
                f"({historical_avg_shaped_rps}) by {variance * 100:+.0f}%; review recommended."
            )
    return result, f"Forecast peak RPS changes from {before} to {after}; prepare {pods} app pods."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    result["peak_rps_assessment"] = assessment.get("peak_rps_assessment")
    result["pod_recommendation"] = assessment.get("pod_recommendation")
    result["risk"] = assessment.get("risk")
    return result
