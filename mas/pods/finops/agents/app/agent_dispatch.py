from __future__ import annotations

from typing import Any

from app import agent_logic
from app.agent_support import call_llm, standard_response


def run_agent(agent_key: str, context: dict[str, Any]) -> dict[str, Any]:
    if agent_key != agent_logic.AGENT_KEY:
        raise ValueError(
            f"image owns agent '{agent_logic.AGENT_KEY}', but received '{agent_key}'"
        )

    result, message = agent_logic.evaluate(context)
    prompt = getattr(agent_logic, "LLM_PROMPT", None)
    assessment = call_llm(prompt, _llm_context(agent_key, context, result)) if prompt else None
    result["llm_assessment"] = assessment
    result["reasoning_source"] = "llm" if assessment else "rule_based"
    if assessment:
        result = agent_logic.apply_llm(result, assessment)

    return standard_response(
        agent_key,
        agent_logic.AGENT_NAME,
        result,
        message,
        context.get("agent_results", {}),
    )


def _llm_context(
    agent_key: str,
    context: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "agent_key": agent_key,
        "event": context.get("event", {}),
        "policy": context.get("policy", {}),
        "business": context.get("business", {}),
        "traffic": context.get("traffic", {}),
        "infra": context.get("infra", {}),
        "signals": context.get("signals", {}),
        "cost_source": context.get("cost_source", {}),
        "policy_source": context.get("policy_source", {}),
        "previous_agent_results": context.get("agent_results", {}),
        "rule_based_result": result,
    }
