from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result
from contracts.models import AgentResponse, AgentStatus, DataRequest


AGENT_KEY = "bottleneck_capacity"
AGENT_NAME = "Bottleneck Capacity Agent"
LLM_PROMPT = (
    "Assess bottleneck risk and actions from RDS CPU, Redis cache hit ratio, ALB health, "
    "pod readiness, and forecast RPS. Return JSON exactly like "
    '{"bottleneck_risk": "low|medium|high", "recommended_action": "..."}.'
)


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str] | AgentResponse:
    signals = context.get("signals", {})
    infra = context.get("infra", {})
    forecast = get_agent_result(context, "traffic_forecast")
    try:
        cluster_state = get_agent_result(context, "cluster_state")
    except KeyError:
        cluster_state = {}
    db_cpu = (
        cluster_state.get("rds_cpu_percent")
        or infra.get("rds_cpu_percent")
        or signals.get("db_cpu_percent")
        or 68
    )
    rds_connections = (
        cluster_state.get("rds_connections")
        or infra.get("rds_connections")
        or signals.get("rds_connections")
        or 640
    )
    rds_source = cluster_state.get("rds_source", "seed")
    cache_hit = infra.get("redis_cache_hit_ratio_percent", signals.get("cache_hit_ratio_percent", 91))
    broker_data = context.get("broker_results", {}).get("traffic_forecast", {})

    if (
        float(db_cpu) > 80
        and forecast["peak_rps_after"] > 1000
        and not broker_data
    ):
        return AgentResponse(
            status=AgentStatus.NEEDS_DATA,
            agent_key=AGENT_KEY,
            agent_name=AGENT_NAME,
            result={},
            message="DB 병목 완화를 위해 20분 분산 조건으로 재예측 요청",
            evidence=[
                f"DB CPU가 {db_cpu}%입니다.",
                f"예측 peak RPS가 {forecast['peak_rps_after']}입니다.",
                "DB CPU가 80%를 초과하고 peak RPS가 1000을 초과해 Traffic Forecast 재예측을 요청합니다.",
            ],
            data_requests=[
                DataRequest(
                    target_agent="traffic_forecast",
                    operation="reforecast",
                    parameters={"push_window_minutes": 20},
                    required_fields=["peak_rps_after", "required_app_pods"],
                    reason="DB CPU가 80%를 초과해 Push 분산을 늘린 조건으로 재예측 필요",
                )
            ],
            confidence=0.7,
            warnings=["DB CPU critical, requesting reforecast"],
            reasoning_source="rule",
        )

    effective_rps = broker_data.get("peak_rps_after", forecast["peak_rps_after"])
    required_pods = broker_data.get("required_app_pods", forecast.get("required_app_pods"))
    live = context.get("live", {}).get("commands", {})
    live_enabled = any(command.get("status") == "ok" for command in live.values())
    result = {
        "db_cpu": f"{db_cpu}%",
        "rds_connections": rds_connections,
        "rds_data_source": rds_source,
        "rds_read_iops": infra.get("rds_read_iops"),
        "cache_hit_ratio": f"{cache_hit}%",
        "alb_status": signals.get("alb_status", "ok"),
        "alb_healthy_targets": infra.get("alb_healthy_targets"),
        "alb_unhealthy_targets": infra.get("alb_unhealthy_targets"),
        "ready_pods": infra.get("ready_pods"),
        "running_pods": infra.get("running_pods"),
        "source": "kubectl+infra_capacity_signal" if live_enabled else "infra_capacity_signal",
        "status": "warning" if db_cpu >= 65 or cache_hit < 93 else "ok",
        "validated_rps": effective_rps,
        "required_app_pods": required_pods,
        "evidence": [
            f"검증 대상 RPS는 {effective_rps}입니다.",
            f"DB CPU는 {db_cpu}%입니다.",
            f"Redis cache hit ratio는 {cache_hit}%입니다.",
            f"ALB 상태는 {signals.get('alb_status', 'ok')}입니다.",
            f"필요 app pod 수는 {required_pods}개입니다.",
            f"데이터 source는 {'kubectl+infra_capacity_signal' if live_enabled else 'infra_capacity_signal'}입니다.",
        ],
    }
    if rds_source == "cloudwatch":
        result["data_quality"] = "realtime_cloudwatch"
    elif rds_source == "cloudwatch_failed":
        result["data_quality"] = "cloudwatch_failed_seed_fallback"
        result.setdefault("warnings", []).append(
            "CloudWatch lookup failed; using seeded RDS capacity data."
        )
    else:
        result["data_quality"] = "seed"
    message = f"Validated {effective_rps} RPS against DB, cache, ALB, and pod capacity."

    if broker_data.get("_broker_status") == "failed":
        result.update(
            {
                "reforecast_applied": False,
                "broker_result": broker_data,
                "warnings": ["broker reforecast failed, using original forecast"],
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
                "risk_level": risk_assessment.get("level", "medium"),
                "warnings": ["Pod readiness constraint applied to forecast"],
            }
        )
        return result, "Reforecast applied with pod readiness constraints"

    return result, message


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    risk = assessment.get("bottleneck_risk")
    result["bottleneck_risk"] = risk
    result["recommended_action"] = assessment.get("recommended_action")
    if risk in {"medium", "high"}:
        result["status"] = "warning"
    return result
