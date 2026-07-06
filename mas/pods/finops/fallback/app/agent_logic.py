from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "fallback"
AGENT_NAME = "Fallback Planner"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    policy = get_agent_result(context, "policy_guardrail")
    result = {
        "vip_only": True,
        "general_hold": True,
        "static_report": True,
        "allowed_actions": policy.get("allowed", []),
        "excluded_actions": policy.get("forbidden", []),
        "evidence": [
            f"Policy Guardrail Agent의 allowed actions={policy.get('allowed', [])} 값을 사용했습니다.",
            f"Policy Guardrail Agent의 forbidden actions={policy.get('forbidden', [])} 값을 사용했습니다.",
            "Fallback은 VIP-only, general hold, static report 전략으로 구성했습니다.",
            "금지된 action은 fallback 계획에서 제외했습니다.",
        ],
    }
    return result, "Prepared a VIP-only fallback with general delivery hold and static reporting."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
