from __future__ import annotations

import asyncio
from typing import Any

from app import agent_logic
from app.agent_support import (
    handle_broker_request,
    llm_judge_data_request,
    llm_judge_policy_risk,
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
    if agent_key == "policy_guardrail":
        risk_analysis = await llm_judge_policy_risk(agent_key, context, result)
        if risk_analysis is not None:
            existing_warnings = result.get("warnings", [])
            if isinstance(existing_warnings, str):
                existing_warnings = [existing_warnings]
            elif not isinstance(existing_warnings, list):
                existing_warnings = []

            result["warnings"] = existing_warnings + risk_analysis.get("warnings", [])
            result["risk_level"] = risk_analysis.get("risk_level")
            result["risk_summary"] = risk_analysis.get("risk_summary")
            result["llm_risk_recommendation"] = risk_analysis.get("recommendation")
            return standard_response(
                agent_key,
                agent_logic.AGENT_NAME,
                result,
                message,
                context.get("agent_results", {}),
                "rule+llm",
            )

        return standard_response(
            agent_key,
            agent_logic.AGENT_NAME,
            result,
            message,
            context.get("agent_results", {}),
            "rule",
        )

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

    return standard_response(
        agent_key,
        agent_logic.AGENT_NAME,
        result,
        message,
        context.get("agent_results", {}),
        "rule",
    )
