from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result
from contracts.models import AgentResponse, AgentStatus


AGENT_KEY = "policy_guardrail"
AGENT_NAME = "Policy Guardrail Agent"
LLM_PROMPT = (
    "Review whether execution should proceed given event value, cost ratio, approval "
    "requirements, allowed actions, and forbidden actions. Return JSON exactly like "
    '{"proceed": true, "conditions": ["..."], "reasoning": "..."}.'
)


def _build_rule_result(context: dict[str, Any]) -> dict[str, Any]:
    policy = context["policy"]
    source = context.get("policy_source", {})
    unit = get_agent_result(context, "unit_economics")
    result = {
        "allowed": source.get("allowed_actions", ["scale_out", "prewarm", "spread_push"]),
        "forbidden": source.get("forbidden_actions", []),
        "approval_required": policy.get("approval_required", True),
        "cost_ratio": unit.get("cost_ratio"),
        "monthly_budget_limit_usd": source.get("monthly_budget_limit_usd"),
        "approval_required_over_usd": source.get("approval_required_over_usd"),
        "policy_version": source.get("policy_version"),
    }

    result["evidence"] = [
        f"Unit Economics Agent의 cost_ratio={unit.get('cost_ratio')} 값을 사용했습니다.",
        f"허용된 actions={result['allowed']}입니다.",
        f"금지된 actions={result['forbidden']}입니다.",
        f"approval_required={result['approval_required']}입니다.",
        f"월 예산 한도는 ${result['monthly_budget_limit_usd']}입니다.",
        f"승인 필요 기준 금액은 ${result['approval_required_over_usd']}입니다.",
        f"정책 버전은 {result['policy_version']}입니다.",
    ]

    return result

def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str] | AgentResponse:
    result = _build_rule_result(context)
    broker_data = context.get("broker_results", {}).get("unit_economics")
    if broker_data is not None:
        broker_failed = broker_data.get("_broker_status") == "failed"
        supported_fields = {
            key: value
            for key, value in broker_data.items()
            if not key.startswith("_")
        }
        if broker_failed or not supported_fields:
            result["approval_required"] = True
            result["unit_economics_additional_validation"] = "unavailable"
            response = AgentResponse(
                status=AgentStatus.COMPLETED,
                agent_key=AGENT_KEY,
                agent_name=AGENT_NAME,
                result=result,
                message=(
                    "Validated proposed actions with rule-based policy because "
                    "unit economics additional validation was unavailable."
                ),
                evidence=[
                    "Used upstream result Unit Economics Agent.cost_ratio",
                    *result.get("evidence", []),
                ],
                data_requests=[],
                confidence=0.72,
                warnings=[
                    "unit_economics additional validation unavailable, using rule-based result"
                ],
                reasoning_source="rule",
            )
            return response

        result["unit_economics_additional_validation"] = supported_fields
        if str(supported_fields.get("final_approval_recommendation", "")).lower() in {
            "requires_human_approval",
            "requires_review",
            "reject",
        }:
            result["approval_required"] = True
        response = AgentResponse(
            status=AgentStatus.COMPLETED,
            agent_key=AGENT_KEY,
            agent_name=AGENT_NAME,
            result=result,
            message="Validated proposed actions with unit economics additional validation.",
            evidence=[
                "Used upstream result Unit Economics Agent.cost_ratio",
                "Used broker result unit_economics additional validation",
                *result.get("evidence", []),
            ],
            data_requests=[],
            confidence=0.86,
            warnings=[],
            reasoning_source="rule",
        )
        return response

    return result, "Validated proposed actions against budget, approval, and forbidden-action policies."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    if isinstance(assessment.get("proceed"), bool):
        result["proceed"] = assessment["proceed"]
    result["conditions"] = assessment.get("conditions", [])
    result["policy_reasoning"] = assessment.get("reasoning")
    return result
