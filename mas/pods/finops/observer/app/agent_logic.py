from __future__ import annotations

from typing import Any


AGENT_KEY = "observer"
AGENT_NAME = "Observer Agent"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    threshold = context.get("signals", {}).get("scale_down_rps_threshold", 600)
    result = {
        "mode": "armed",
        "watch": ["rps", "latency", "db_cpu", "cost_burn"],
        "recommendation": f"scale_down_if_actual_rps_below_{threshold}",
    }
    return result, f"Monitor runtime signals and recommend scale-down below {threshold} actual RPS."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
