from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "unit_economics"
AGENT_NAME = "Unit Economics Agent"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    signals = context.get("signals", {})
    cost = get_agent_result(context, "cost")
    expected_value = float(signals.get("expected_value_usd", 4200))
    ratio = round((cost["total"] / expected_value) * 100, 1) if expected_value else 100.0
    result = {
        "expected_value_usd": expected_value,
        "cost_ratio": f"{ratio}%",
        "override": ratio > 5,
        "estimated_cost_usd": cost["total"],
    }
    return result, f"Incremental cost is {ratio}% of the expected business value."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
