from __future__ import annotations

from typing import Any


AGENT_KEY = "fallback"
AGENT_NAME = "Fallback Planner"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    policy = context["agent_results"]["policy_guardrail"]
    result = {
        "vip_only": True,
        "general_hold": True,
        "static_report": True,
        "allowed_actions": policy.get("allowed", []),
        "excluded_actions": policy.get("forbidden", []),
    }
    return result, "Prepared a VIP-only fallback with general delivery hold and static reporting."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
