from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "postmortem_learning"
AGENT_NAME = "Postmortem Learning Agent"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    forecast = get_agent_result(context, "traffic_forecast")
    cost = get_agent_result(context, "cost")
    result = {
        "profile_update": "pending_after_execution",
        "compare": ["forecast", "actual", "cost"],
        "forecast_peak_rps": forecast.get("peak_rps_after"),
        "forecast_cost_usd": cost.get("total"),
    }
    return result, "Prepared forecast-versus-actual and estimated-versus-actual cost comparisons."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
