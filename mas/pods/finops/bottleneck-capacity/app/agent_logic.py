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
    db_cpu = infra.get("rds_cpu_percent", signals.get("db_cpu_percent", 68))
    cache_hit = infra.get("redis_cache_hit_ratio_percent", signals.get("cache_hit_ratio_percent", 91))
    broker_data = context.get("broker_results", {}).get("traffic_forecast", {})

    if broker_data.get("_broker_status") == "failed":
        return AgentResponse(
            status=AgentStatus.REQUIRES_REVIEW,
            agent_key=AGENT_KEY,
            agent_name=AGENT_NAME,
            result={"status": "warning", "broker_result": broker_data},
            message="DB 병목 재예측 요청을 해결하지 못해 운영자 검토가 필요합니다.",
            evidence=[f"DB CPU: {db_cpu}%", f"Forecast RPS: {forecast['peak_rps_after']}"],
            data_requests=[],
            confidence=0.5,
            warnings=[broker_data.get("_broker_message", "Broker request failed")],
            reasoning_source="rule",
        )

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
            evidence=[],
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
        "rds_connections": infra.get("rds_connections"),
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
    }
    message = f"Validated {effective_rps} RPS against DB, cache, ALB, and pod capacity."
    if broker_data.get("_broker_status") == "completed":
        return AgentResponse(
            status=AgentStatus.COMPLETED,
            agent_key=AGENT_KEY,
            agent_name=AGENT_NAME,
            result=result,
            message=message,
            evidence=[
                "Used Temporal Data Broker traffic reforecast",
                f"Reforecast RPS: {effective_rps}",
                f"Required app pods: {required_pods}",
            ],
            data_requests=[],
            confidence=0.8,
            warnings=[],
            reasoning_source="rule",
        )
    return result, message


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    risk = assessment.get("bottleneck_risk")
    result["bottleneck_risk"] = risk
    result["recommended_action"] = assessment.get("recommended_action")
    if risk in {"medium", "high"}:
        result["status"] = "warning"
    return result
