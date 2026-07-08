from __future__ import annotations

import math
import os
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
    business_control = _optional_agent_result(context, "business_control")
    cluster_state = _optional_agent_result(context, "cluster_state")

    parameters = context.get("parameters", {})
    broker_data = context.get("broker_results", {}).get("traffic_forecast", {})
    before = int(
        business_control.get("baseline_peak_rps")
        or context.get("baseline_peak_rps")
        or signals.get("baseline_peak_rps")
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
        return _evaluate_readiness_reforecast(
            context=context,
            policy=policy,
            signals=signals,
            traffic=traffic,
            shaping=shaping,
            parameters=parameters,
            before=before,
        )

    current_pods = _current_pods(cluster_state, traffic, signals)
    candidate_forecasts = _build_candidate_forecasts(
        shaping_candidates=shaping.get("candidates", []),
        current_pods=current_pods,
    )
    if candidate_forecasts:
        selected = candidate_forecasts[0]
        after = selected["peak_rps_after"]
        pods = selected["required_app_pods"]
        estimated_p95 = selected["estimated_p95_ms"]
        window = selected["push_window_minutes"]
        result = {
            "peak_rps_before": before,
            "peak_rps_after": after,
            "required_app_pods": pods,
            "current_pods": selected["current_pods"],
            "scale_out_pods": selected["scale_out_pods"],
            "estimated_p95_ms": estimated_p95,
            "p95_latency_ms": estimated_p95,
            "vip_peak_rps": selected["vip_peak_rps"],
            "general_peak_rps": selected["general_peak_rps"],
            "based_on": "demand_shaping_user_behavior_model",
            "send_window_minutes": window,
            "vip_send_mode": selected["vip_send_mode"],
            "general_send_mode": selected["general_send_mode"],
            "per_minute_general": selected["per_minute_general"],
            "per_second_general": selected["per_second_general"],
            "reforecast": False,
            "candidate_forecasts": candidate_forecasts,
            "alb_request_count_5m": traffic.get("alb_request_count_5m"),
            "queue_depth": traffic.get("queue_depth"),
            "hpa_current_replicas": traffic.get("hpa_current_replicas"),
            "hpa_current_cpu_utilization_percent": traffic.get(
                "hpa_current_cpu_utilization_percent"
            ),
            "source": _source(context),
            "model_assumptions": {
                "app_open_rate_vip": _env_float("APP_OPEN_RATE_VIP", 0.35),
                "app_open_rate_general": _env_float("APP_OPEN_RATE_GENERAL", 0.30),
                "requests_per_open": _env_float("REQUESTS_PER_OPEN", 3.0),
                "vip_open_window_seconds": _env_float("VIP_OPEN_WINDOW_SECONDS", 30.0),
                "rps_per_pod": _env_float("RPS_PER_POD", 28.0),
            },
            "evidence": [
                f"과거 기준 peak RPS는 {before}입니다.",
                f"VIP 즉시 발송 피크 RPS는 {selected['vip_peak_rps']}입니다.",
                f"일반 사용자 분산 발송 피크 RPS는 {selected['general_peak_rps']}입니다.",
                f"총 예상 peak RPS는 {after}입니다.",
                f"필요 app pod 수는 {pods}개입니다.",
                (
                    f"현재 pod 수는 {selected['current_pods']}개이고 "
                    f"추가 증설 pod 수는 {selected['scale_out_pods']}개입니다."
                ),
            ],
        }
        _append_history_variance(result, business_control, after)
        return result, f"Forecast peak RPS is {after}; prepare {pods} app pods."

    return _evaluate_fallback(
        context=context,
        policy=policy,
        signals=signals,
        traffic=traffic,
        shaping=shaping,
        broker_data=broker_data,
        business_control=business_control,
        before=before,
    )


def _optional_agent_result(context: dict[str, Any], agent_key: str) -> dict[str, Any]:
    try:
        return get_agent_result(context, agent_key)
    except KeyError:
        return {}


def _build_candidate_forecasts(
    *,
    shaping_candidates: list[dict[str, Any]],
    current_pods: int,
) -> list[dict[str, Any]]:
    if not shaping_candidates:
        return []

    app_open_rate_vip = _env_float("APP_OPEN_RATE_VIP", 0.35)
    app_open_rate_general = _env_float("APP_OPEN_RATE_GENERAL", 0.30)
    requests_per_open = _env_float("REQUESTS_PER_OPEN", 3.0)
    vip_open_window_seconds = _env_float("VIP_OPEN_WINDOW_SECONDS", 30.0)
    rps_per_pod = _env_float("RPS_PER_POD", 28.0)

    forecasts: list[dict[str, Any]] = []
    for candidate in shaping_candidates:
        vip_count = int(candidate.get("vip_count") or 0)
        general_count = int(candidate.get("general_count") or 0)
        window = int(
            candidate.get("send_window_minutes")
            or candidate.get("push_window_minutes")
            or 1
        )
        per_minute_general = float(
            candidate.get("per_minute_general")
            or general_count / max(window, 1)
        )
        per_second_general = float(
            candidate.get("per_second_general")
            or general_count / max(window * 60, 1)
        )
        vip_peak_rps = round(
            vip_count * app_open_rate_vip * requests_per_open / vip_open_window_seconds
        )
        general_peak_rps = round(
            per_second_general * app_open_rate_general * requests_per_open
        )
        total_peak_rps = int(vip_peak_rps + general_peak_rps)
        required_pods = max(1, math.ceil(total_peak_rps / max(rps_per_pod, 1)))
        scale_out_pods = max(0, required_pods - current_pods)
        load_per_pod = total_peak_rps / max(required_pods, 1)
        estimated_p95_ms = round(100 + load_per_pod * 3.2)
        forecasts.append(
            {
                "label": candidate["label"],
                "push_window_minutes": window,
                "send_window_minutes": window,
                "vip_send_mode": candidate.get("vip_send_mode"),
                "general_send_mode": candidate.get("general_send_mode"),
                "per_minute_general": per_minute_general,
                "per_second_general": per_second_general,
                "vip_peak_rps": vip_peak_rps,
                "general_peak_rps": general_peak_rps,
                "peak_rps_after": total_peak_rps,
                "required_app_pods": required_pods,
                "current_pods": current_pods,
                "scale_out_pods": scale_out_pods,
                "estimated_p95_ms": estimated_p95_ms,
            }
        )
    return forecasts


def _current_pods(
    cluster_state: dict[str, Any],
    traffic: dict[str, Any],
    signals: dict[str, Any],
) -> int:
    return int(
        cluster_state.get("scale_target_current_pods")
        or traffic.get("hpa_current_replicas")
        or signals.get("current_app_pods")
        or signals.get("required_app_pods")
        or 0
    )


def _evaluate_readiness_reforecast(
    *,
    context: dict[str, Any],
    policy: dict[str, Any],
    signals: dict[str, Any],
    traffic: dict[str, Any],
    shaping: dict[str, Any],
    parameters: dict[str, Any],
    before: int,
) -> tuple[dict[str, Any], str]:
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

    pod_scaling_timeline = "T-25m (추가 준비 시간 필요)" if ready_ratio < 0.7 else "T-20m"

    result = {
        "peak_rps_before": before,
        "peak_rps_after": peak_rps_after,
        "required_app_pods": required_app_pods,
        "based_on": "pod_readiness_constraints",
        "send_window_minutes": shaping.get("send_window_minutes")
        or policy["max_general_delay_minutes"],
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
        "estimated_p95_ms": p95_latency_ms,
        "queue_depth": queue_depth,
        "pod_memory_percent": pod_memory_percent,
        "hpa_current_replicas": traffic.get("hpa_current_replicas"),
        "hpa_current_cpu_utilization_percent": traffic.get(
            "hpa_current_cpu_utilization_percent"
        ),
        "source": _source(context),
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


def _evaluate_fallback(
    *,
    context: dict[str, Any],
    policy: dict[str, Any],
    signals: dict[str, Any],
    traffic: dict[str, Any],
    shaping: dict[str, Any],
    broker_data: dict[str, Any],
    business_control: dict[str, Any],
    before: int,
) -> tuple[dict[str, Any], str]:
    parameter_window = context.get("parameters", {}).get("push_window_minutes")
    broker_window = broker_data.get("push_window_minutes")
    window = (
        parameter_window
        or broker_window
        or shaping.get("send_window_minutes")
        or policy["max_general_delay_minutes"]
    )
    reforecast = parameter_window is not None or broker_window is not None
    reduction = shaping.get(
        "peak_reduction_percent",
        min(60, max(10, int(window * 4.2))),
    )
    after = max(1, int(before * (100 - reduction) / 100))
    pods = traffic.get("hpa_desired_replicas", signals.get("required_app_pods", 29))
    current_pods = int(traffic.get("hpa_current_replicas") or 0)
    estimated_p95 = float(traffic.get("p95_latency_ms") or 0.0)
    result = {
        "peak_rps_before": before,
        "peak_rps_after": after,
        "required_app_pods": pods,
        "current_pods": current_pods,
        "scale_out_pods": max(0, int(pods) - current_pods),
        "based_on": "fallback_baseline_reduction",
        "send_window_minutes": window,
        "peak_reduction_percent": reduction,
        "vip_send_mode": shaping.get("vip_send_mode"),
        "general_send_mode": shaping.get("general_send_mode"),
        "reforecast": reforecast,
        "candidate_forecasts": [],
        "alb_request_count_5m": traffic.get("alb_request_count_5m"),
        "p95_latency_ms": estimated_p95,
        "estimated_p95_ms": estimated_p95,
        "queue_depth": traffic.get("queue_depth"),
        "hpa_current_replicas": traffic.get("hpa_current_replicas"),
        "hpa_current_cpu_utilization_percent": traffic.get(
            "hpa_current_cpu_utilization_percent"
        ),
        "source": _source(context),
        "evidence": [
            f"기준 peak RPS는 {before}입니다.",
            f"Demand Shaping 후보가 없어 fallback 감소율 {reduction}%를 사용했습니다.",
            f"계산식은 {before} * (100 - {reduction}) / 100 = {after} RPS입니다.",
            f"필요 app pod 수는 {pods}개로 산정했습니다.",
        ],
    }
    _append_history_variance(result, business_control, after)
    return result, f"Forecast peak RPS changes from {before} to {after}; prepare {pods} app pods."


def _append_history_variance(
    result: dict[str, Any],
    business_control: dict[str, Any],
    after: int | float,
) -> None:
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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _source(context: dict[str, Any]) -> str:
    live = context.get("live", {}).get("commands", {})
    live_enabled = any(command.get("status") == "ok" for command in live.values())
    return "kubectl" if live_enabled else "traffic_observability_signal"


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    result["peak_rps_assessment"] = assessment.get("peak_rps_assessment")
    result["pod_recommendation"] = assessment.get("pod_recommendation")
    result["risk"] = assessment.get("risk")
    return result
