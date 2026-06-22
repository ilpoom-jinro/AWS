from __future__ import annotations

from typing import Any


AGENT_KEY = "postmortem_learning"
AGENT_NAME = "Postmortem Learning Agent"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    forecast = context["agent_results"]["traffic_forecast"]
    cost = context["agent_results"]["cost"]
    result = {
        "profile_update": "pending_after_execution",
        "compare": ["forecast", "actual", "cost"],
        "forecast_peak_rps": forecast.get("peak_rps_after"),
        "forecast_cost_usd": cost.get("total"),
    }
    return result, "Prepared forecast-versus-actual and estimated-versus-actual cost comparisons."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
