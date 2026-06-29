from __future__ import annotations

import asyncio
from typing import Any

from app import agent_logic
from app.agent_support import (
    call_llm,
    handle_broker_request,
    llm_judge_data_request,
    standard_response,
)
from contracts.models import AGENT_ALLOWED_REQUESTS, AgentResponse, AgentStatus


def run_agent(agent_key: str, context: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(run_agent_async(agent_key, context))


async def run_agent_async(agent_key: str, context: dict[str, Any]) -> dict[str, Any]:
    if agent_key != agent_logic.AGENT_KEY:
        raise ValueError(
            f"image owns agent '{agent_logic.AGENT_KEY}', but received '{agent_key}'"
        )

    parameters = context.get("parameters", {})
    broker_operation = parameters.get("operation") or context.get("_broker_operation")
    if parameters.get("_broker_request") is True or context.get("_broker_operation"):
        required_fields = context.get("_broker_required_fields", [])
        broker_result = await handle_broker_request(
            agent_key=agent_key,
            agent_name=agent_logic.AGENT_NAME,
            operation=broker_operation,
            parameters=parameters,
            required_fields=required_fields,
            context=context,
        )
        if broker_result is None:
            response = AgentResponse(
                status=AgentStatus.COMPLETED,
                agent_key=agent_key,
                agent_name=agent_logic.AGENT_NAME,
                result={
                    "_broker_handled": False,
                    "_broker_reason": "not_applicable",
                },
                message=f"Broker operation '{broker_operation}' not applicable",
                evidence=[],
                data_requests=[],
                confidence=0.5,
                warnings=[f"broker operation '{broker_operation}' not handled by this agent"],
                reasoning_source="rule",
            )
            return response.model_dump(mode="json")

        response = AgentResponse(
            status=AgentStatus.COMPLETED,
            agent_key=agent_key,
            agent_name=agent_logic.AGENT_NAME,
            result=broker_result,
            message=f"Broker operation '{broker_operation}' handled",
            evidence=[],
            data_requests=[],
            confidence=0.8,
            warnings=[],
            reasoning_source="llm",
        )
        return response.model_dump(mode="json")

    evaluation = agent_logic.evaluate(context)
    if isinstance(evaluation, AgentResponse):
        return evaluation.model_dump(mode="json")

    result, message = evaluation
    allowed_targets = AGENT_ALLOWED_REQUESTS.get(agent_key, [])
    if allowed_targets:
        data_request = await llm_judge_data_request(
            agent_key,
            context,
            result,
            allowed_targets,
        )
        if data_request is not None:
            response = AgentResponse(
                status=AgentStatus.NEEDS_DATA,
                agent_key=agent_key,
                agent_name=agent_logic.AGENT_NAME,
                result={},
                message=data_request.reason,
                evidence=[],
                data_requests=[data_request],
                confidence=0.6,
                warnings=["LLM judge triggered data request"],
                reasoning_source="llm",
            )
            return response.model_dump(mode="json")

    prompt = getattr(agent_logic, "LLM_PROMPT", None)
    assessment = call_llm(prompt, _llm_context(agent_key, context, result)) if prompt else None
    result["llm_assessment"] = assessment
    if assessment:
        result = agent_logic.apply_llm(result, assessment)

    return standard_response(
        agent_key,
        agent_logic.AGENT_NAME,
        result,
        message,
        context.get("agent_results", {}),
        "rule+llm" if assessment else "rule",
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
