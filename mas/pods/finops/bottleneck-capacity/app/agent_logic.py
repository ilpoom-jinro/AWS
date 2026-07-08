from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result
from contracts.models import AgentResponse, AgentStatus, DataRequest


AGENT_KEY = "bottleneck_capacity"
AGENT_NAME = "Bottleneck Capacity Agent"
LLM_PROMPT = (
    "Assess bottleneck risk and actions from RDS CPU, Redis cache hit ratio, ALB health, "
    "pod readiness, and forecast RPS. Return JSON exactly like "
    '{"bottleneck_risk": "low|warning|critical", "recommended_action": "..."}.'
)

DB_CPU_WARNING = 65.0
DB_CPU_CRITICAL = 80.0


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str] | AgentResponse:
    signals = context.get("signals", {})
    infra = context.get("infra", {})
    forecast = get_agent_result(context, "traffic_forecast")
    cluster_state = _optional_agent_result(context, "cluster_state")
    broker_data = context.get("broker_results", {}).get("traffic_forecast", {})

    rds_state = _resolve_rds_state(context, cluster_state, infra, signals)
    db_cpu = rds_state["rds_cpu"]
    rds_connections = rds_state["rds_connections"]
    rds_source = rds_state["rds_source"]
    cache_hit = _as_float(
        infra.get("redis_cache_hit_ratio_percent")
        or signals.get("cache_hit_ratio_percent")
        or context.get("redis_cache_hit_ratio_percent")
        or context.get("cache_hit_ratio")
        or 91
    )

    effective_rps = _as_float(broker_data.get("peak_rps_after") or forecast["peak_rps_after"])
    required_pods = int(broker_data.get("required_app_pods") or forecast.get("required_app_pods") or 1)
    ready_pods = int(
        cluster_state.get("scale_target_current_pods")
        or infra.get("ready_pods")
        or context.get("ready_app_pods")
        or context.get("ready_pods")
        or 15
    )
    pod_readiness_ratio = round(ready_pods / max(required_pods, 1), 2)
    pod_readiness_percent = round(pod_readiness_ratio * 100, 1)
    pod_readiness_warning = pod_readiness_ratio < 0.7

    current_rps = _as_float(
        signals.get("prometheus_rps")
        or context.get("prometheus_rps")
        or signals.get("alb_request_count_5m")
        or context.get("alb_request_count_5m")
        or 200
    )
    estimated_rds_cpu_at_peak = _estimate_rds_cpu_at_peak(
        rds_cpu=rds_state["rds_cpu"],
        current_rps=current_rps,
        peak_rps=effective_rps,
    )
    db_risk = _db_risk(estimated_rds_cpu_at_peak, rds_state["rds_cpu"])
    bottleneck_risk = _bottleneck_risk(db_risk, pod_readiness_ratio)
    warnings = _build_warnings(
        rds_source=rds_source,
        pod_readiness_warning=pod_readiness_warning,
        pod_readiness_percent=pod_readiness_percent,
        ready_pods=ready_pods,
        required_pods=required_pods,
        estimated_rds_cpu_at_peak=estimated_rds_cpu_at_peak,
        peak_rps=effective_rps,
        db_risk=db_risk,
    )

    if (
        db_cpu > DB_CPU_CRITICAL
        and effective_rps > 1000
        and not broker_data
        and rds_source != "cloudwatch"
    ):
        return AgentResponse(
            status=AgentStatus.NEEDS_DATA,
            agent_key=AGENT_KEY,
            agent_name=AGENT_NAME,
            result={},
            message="DB bottleneck risk is critical; requesting traffic reforecast.",
            evidence=[
                f"DB CPU is {db_cpu}%.",
                f"Forecast peak RPS is {effective_rps}.",
                "DB risk is critical and peak RPS is over 1000; requesting Traffic Forecast reforecast.",
            ],
            data_requests=[
                DataRequest(
                    target_agent="traffic_forecast",
                    operation="reforecast",
                    parameters={"push_window_minutes": 20},
                    required_fields=["peak_rps_after", "required_app_pods"],
                    reason="DB bottleneck risk requires a longer push distribution reforecast.",
                )
            ],
            confidence=0.7,
            warnings=["DB CPU critical, requesting reforecast"],
            reasoning_source="rule",
        )

    live = context.get("live", {}).get("commands", {})
    live_enabled = any(command.get("status") == "ok" for command in live.values())
    data_quality = _data_quality(rds_source)
    source = "cloudwatch+kubectl" if rds_source == "cloudwatch" else "seed+kubectl"
    if not live_enabled and rds_source != "cloudwatch":
        source = "seed+infra_capacity_signal"
    elif not live_enabled:
        source = "cloudwatch+infra_capacity_signal"

    result = {
        "db_cpu": db_cpu,
        "rds_connections": rds_connections,
        "rds_data_source": rds_source,
        "rds_read_iops": infra.get("rds_read_iops"),
        "cache_hit_ratio": cache_hit,
        "alb_status": signals.get("alb_status", "ok"),
        "alb_healthy_targets": infra.get("alb_healthy_targets"),
        "alb_unhealthy_targets": infra.get("alb_unhealthy_targets"),
        "ready_pods": ready_pods,
        "running_pods": infra.get("running_pods"),
        "required_pods": required_pods,
        "required_app_pods": required_pods,
        "pod_readiness_ratio": pod_readiness_ratio,
        "pod_readiness_percent": pod_readiness_percent,
        "pod_readiness_warning": pod_readiness_warning,
        "current_rps": current_rps,
        "peak_rps_forecast": effective_rps,
        "estimated_rds_cpu_at_peak": estimated_rds_cpu_at_peak,
        "db_risk": db_risk,
        "bottleneck_risk": bottleneck_risk,
        "risk_level": bottleneck_risk,
        "status": "warning" if bottleneck_risk != "low" or cache_hit < 93 else "ok",
        "validated_rps": effective_rps,
        "data_quality": data_quality,
        "warnings": warnings,
        "source": source,
        "evidence": [
            f"Validated peak RPS is {effective_rps}.",
            f"DB CPU is {db_cpu}% from {rds_source}.",
            f"Estimated DB CPU at peak is {estimated_rds_cpu_at_peak or 'N/A'}%.",
            f"Pod readiness is {pod_readiness_percent}% ({ready_pods}/{required_pods}).",
            f"Redis cache hit ratio is {cache_hit}%.",
            f"ALB status is {signals.get('alb_status', 'ok')}.",
        ],
    }

    if rds_source == "cloudwatch_failed":
        result.setdefault("warnings", []).append(
            "CloudWatch lookup failed; using seeded RDS capacity data."
        )

    message = (
        f"DB CPU {db_cpu}% ({rds_source}), "
        f"pod readiness {pod_readiness_percent}% ({ready_pods}/{required_pods}), "
        f"peak DB CPU estimate {estimated_rds_cpu_at_peak or 'N/A'}%, "
        f"bottleneck risk {bottleneck_risk}."
    )

    if broker_data.get("_broker_status") == "failed":
        result.update(
            {
                "reforecast_applied": False,
                "broker_result": broker_data,
                "warnings": ["broker reforecast failed, using original forecast"] + result["warnings"],
            }
        )
        return result, "Using original forecast: broker reforecast failed"

    if broker_data:
        risk_assessment = broker_data.get("risk_assessment", {})
        result.update(
            {
                "reforecast_applied": True,
                "adjusted_capacity_rps": broker_data.get("adjusted_capacity_rps"),
                "pod_scaling_timeline": broker_data.get("pod_scaling_timeline"),
                "risk_level": risk_assessment.get("level", bottleneck_risk),
                "warnings": result["warnings"] + ["Pod readiness constraint applied to forecast"],
            }
        )
        return result, "Reforecast applied with pod readiness constraints"

    return result, message


def _optional_agent_result(context: dict[str, Any], agent_key: str) -> dict[str, Any]:
    try:
        return get_agent_result(context, agent_key)
    except KeyError:
        return {}


def _resolve_rds_state(
    context: dict[str, Any],
    cluster_state: dict[str, Any],
    infra: dict[str, Any],
    signals: dict[str, Any],
) -> dict[str, Any]:
    rds_metrics = cluster_state.get("rds_metrics", {})
    primary_db = rds_metrics.get("financial-service-db", {})
    fallback_db = rds_metrics.get("financial-ops-db", {})
    metric_source = primary_db.get("source") or fallback_db.get("source")

    rds_cpu = (
        primary_db.get("cpu_percent")
        or fallback_db.get("cpu_percent")
        or cluster_state.get("rds_cpu_percent")
        or infra.get("rds_cpu_percent")
        or signals.get("db_cpu_percent")
        or context.get("rds_cpu_percent")
        or context.get("rds_cpu")
        or 68
    )
    rds_connections = (
        primary_db.get("connections")
        or fallback_db.get("connections")
        or cluster_state.get("rds_connections")
        or infra.get("rds_connections")
        or signals.get("rds_connections")
        or context.get("rds_connections")
        or 640
    )

    if metric_source == "cloudwatch" or cluster_state.get("rds_source") == "cloudwatch":
        rds_source = "cloudwatch"
    elif metric_source == "cloudwatch_failed" or cluster_state.get("rds_source") == "cloudwatch_failed":
        rds_source = "cloudwatch_failed"
    else:
        rds_source = "seed"

    return {
        "rds_cpu": _as_float(rds_cpu),
        "rds_connections": int(_as_float(rds_connections)),
        "rds_source": rds_source,
    }


def _estimate_rds_cpu_at_peak(
    *,
    rds_cpu: float,
    current_rps: float,
    peak_rps: float,
) -> float | None:
    if rds_cpu > 0 and current_rps > 0:
        return round((rds_cpu / current_rps) * peak_rps, 1)
    return None


def _db_risk(estimated_rds_cpu_at_peak: float | None, current_rds_cpu: float) -> str:
    value = estimated_rds_cpu_at_peak if estimated_rds_cpu_at_peak is not None else current_rds_cpu
    if value >= DB_CPU_CRITICAL:
        return "critical"
    if value >= DB_CPU_WARNING:
        return "warning"
    return "low"


def _bottleneck_risk(db_risk: str, pod_readiness_ratio: float) -> str:
    if db_risk == "critical" or pod_readiness_ratio < 0.5:
        return "critical"
    if db_risk == "warning" or pod_readiness_ratio < 0.7:
        return "warning"
    return "low"


def _build_warnings(
    *,
    rds_source: str,
    pod_readiness_warning: bool,
    pod_readiness_percent: float,
    ready_pods: int,
    required_pods: int,
    estimated_rds_cpu_at_peak: float | None,
    peak_rps: float,
    db_risk: str,
) -> list[str]:
    warnings: list[str] = []
    if rds_source != "cloudwatch":
        warnings.append(
            "CloudWatch lookup unavailable; using seeded RDS capacity data. "
            "Manual DB state verification is recommended."
        )
    if pod_readiness_warning:
        warnings.append(
            f"Pod readiness is {pod_readiness_percent}% "
            f"({ready_pods}/{required_pods}); scale-out should complete before the event."
        )
    if estimated_rds_cpu_at_peak is not None and db_risk != "low":
        warnings.append(
            f"Peak RPS {peak_rps} may drive DB CPU to {estimated_rds_cpu_at_peak}%; "
            f"DB bottleneck risk is {db_risk}."
        )
    return warnings


def _data_quality(rds_source: str) -> str:
    if rds_source == "cloudwatch":
        return "realtime_cloudwatch"
    if rds_source == "cloudwatch_failed":
        return "cloudwatch_failed_seed_fallback"
    return "seed"


def _as_float(value: Any) -> float:
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    risk = assessment.get("bottleneck_risk")
    result["bottleneck_risk"] = risk
    result["recommended_action"] = assessment.get("recommended_action")
    if risk in {"warning", "critical", "medium", "high"}:
        result["status"] = "warning"
    return result
