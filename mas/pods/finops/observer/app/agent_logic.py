from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result
from contracts.models import AgentResponse, AgentStatus


AGENT_KEY = "observer"
AGENT_NAME = "Observer Agent"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str] | AgentResponse:
    forecast = get_agent_result(context, "traffic_forecast")
    policy = get_agent_result(context, "policy_guardrail")
    broker_data = context.get("broker_results", {}).get("traffic_forecast", {})
    threshold = context.get("signals", {}).get("scale_down_rps_threshold", 600)
    if broker_data:
        broker_failed = broker_data.get("_broker_status") == "failed"
        source = forecast if broker_failed else {**forecast, **broker_data}
        result = {
            "mode": "armed",
            "watch": ["rps", "latency", "db_cpu", "cost_burn"],
            "recommendation": f"scale_down_if_actual_rps_below_{threshold}",
            "forecast_peak_rps": source.get("peak_rps_after"),
            "forecast_required_pods": source.get("required_app_pods"),
            "forecast_p95_ms": source.get("estimated_p95_ms")
            or source.get("p95_latency_ms"),
            "approval_required": policy.get("approval_required"),
            "broker_reforecast_applied": not broker_failed,
        }
        warnings = []
        message = "Monitor runtime signals using broker reforecast."
        if broker_failed:
            warnings.append("broker reforecast failed, using existing forecast")
            message = "Monitor runtime signals using existing forecast because broker reforecast failed."
        return AgentResponse(
            status=AgentStatus.COMPLETED,
            agent_key=AGENT_KEY,
            agent_name=AGENT_NAME,
            result=result,
            message=message,
            evidence=["Used Traffic Forecast Agent forecast for observer thresholds"],
            data_requests=[],
            confidence=0.76,
            warnings=warnings,
            reasoning_source="rule",
        )

    result = {
        "mode": "armed",
        "watch": ["rps", "latency", "db_cpu", "cost_burn"],
        "recommendation": f"scale_down_if_actual_rps_below_{threshold}",
        "forecast_peak_rps": forecast.get("peak_rps_after"),
        "approval_required": policy.get("approval_required"),
    }
    return result, f"Monitor runtime signals and recommend scale-down below {threshold} actual RPS."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
