from __future__ import annotations

from typing import Any


AGENT_KEY = "policy_guardrail"
AGENT_NAME = "Policy Guardrail Agent"
LLM_PROMPT = (
    "Review whether execution should proceed given event value, cost ratio, approval "
    "requirements, allowed actions, and forbidden actions. Return JSON exactly like "
    '{"proceed": true, "conditions": ["..."], "reasoning": "..."}.'
)


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    policy = context["policy"]
    source = context.get("policy_source", {})
    unit = context["agent_results"]["unit_economics"]
    result = {
        "allowed": source.get("allowed_actions", ["scale_out", "prewarm", "spread_push"]),
        "forbidden": source.get("forbidden_actions", []),
        "approval_required": policy["approval_required"],
        "cost_ratio": unit["cost_ratio"],
        "monthly_budget_limit_usd": source.get("monthly_budget_limit_usd"),
        "approval_required_over_usd": source.get("approval_required_over_usd"),
        "policy_version": source.get("policy_version"),
    }
    return result, "Validated proposed actions against budget, approval, and forbidden-action policies."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    if isinstance(assessment.get("proceed"), bool):
        result["proceed"] = assessment["proceed"]
    result["conditions"] = assessment.get("conditions", [])
    result["policy_reasoning"] = assessment.get("reasoning")
    return result
