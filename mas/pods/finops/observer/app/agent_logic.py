from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "observer"
AGENT_NAME = "Observer Agent"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    forecast = get_agent_result(context, "traffic_forecast")
    policy = get_agent_result(context, "policy_guardrail")
    threshold = context.get("signals", {}).get("scale_down_rps_threshold", 600)
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
