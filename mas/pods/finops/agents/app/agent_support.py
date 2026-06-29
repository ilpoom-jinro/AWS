from __future__ import annotations

import concurrent.futures
import json
import logging
import os
from typing import Any

from contracts.models import AgentResponse, AgentStatus, DataRequest


logger = logging.getLogger(__name__)
LLM_TIMEOUT_SECONDS = 5
LLM_JUDGE_TIMEOUT_SECONDS = 10
BROKER_REQUEST_TIMEOUT_SECONDS = 15

AGENT_TASK_QUEUES = {
    "business_control": "finops-business-control-agent-task-queue",
    "demand_shaping": "finops-demand-shaping-agent-task-queue",
    "traffic_forecast": "finops-traffic-forecast-agent-task-queue",
    "bottleneck_capacity": "finops-bottleneck-capacity-agent-task-queue",
    "infra_execution": "finops-infra-execution-agent-task-queue",
    "cost": "finops-cost-agent-task-queue",
    "unit_economics": "finops-unit-economics-agent-task-queue",
    "policy_guardrail": "finops-policy-guardrail-agent-task-queue",
    "observer": "finops-observer-agent-task-queue",
    "fallback": "finops-fallback-agent-task-queue",
    "postmortem_learning": "finops-postmortem-learning-agent-task-queue",
}

AGENT_NAMES = {
    "business_control": "Business Control Agent",
    "demand_shaping": "Demand Shaping Agent",
    "traffic_forecast": "Traffic Forecast Agent",
    "bottleneck_capacity": "Bottleneck Capacity Agent",
    "infra_execution": "Infra Execution Planner",
    "cost": "Cost Agent",
    "unit_economics": "Unit Economics Agent",
    "policy_guardrail": "Policy Guardrail Agent",
    "observer": "Observer Agent",
    "fallback": "Fallback Planner",
    "postmortem_learning": "Postmortem Learning Agent",
}

AGENT_CONFIDENCE = {
    "business_control": 0.91,
    "demand_shaping": 0.86,
    "traffic_forecast": 0.82,
    "bottleneck_capacity": 0.78,
    "infra_execution": 0.84,
    "cost": 0.8,
    "unit_economics": 0.79,
    "policy_guardrail": 0.9,
    "observer": 0.76,
    "fallback": 0.88,
    "postmortem_learning": 0.74,
}

AGENT_DEPENDENCIES = {
    "demand_shaping": [("business_control", "max_delay_minutes")],
    "traffic_forecast": [
        ("demand_shaping", "peak_reduction_percent"),
        ("business_control", "target_users"),
    ],
    "bottleneck_capacity": [("traffic_forecast", "peak_rps_after")],
    "infra_execution": [("traffic_forecast", "required_app_pods")],
    "cost": [("infra_execution", "target_app_pods")],
    "unit_economics": [("cost", "total")],
    "policy_guardrail": [("unit_economics", "cost_ratio")],
    "observer": [
        ("traffic_forecast", "peak_rps_after"),
        ("policy_guardrail", "approval_required"),
    ],
    "fallback": [("policy_guardrail", "allowed")],
    "postmortem_learning": [
        ("traffic_forecast", "peak_rps_before"),
        ("cost", "total"),
    ],
}


def call_llm(prompt: str, context_data: dict[str, Any]) -> dict[str, Any] | None:
    def invoke() -> dict[str, Any] | None:
        from shared.bedrock import ClaudeModel, get_bedrock_client

        client = get_bedrock_client()
        response = client.converse(
            modelId=os.getenv("BEDROCK_MODEL", ClaudeModel.HAIKU.value),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": (
                                f"{prompt}\n\nReturn only one valid JSON object.\n\n"
                                f"Context:\n{json.dumps(context_data, ensure_ascii=False, default=str)}"
                            )
                        }
                    ],
                }
            ],
        )
        content = response.get("output", {}).get("message", {}).get("content", [])
        text = "\n".join(item.get("text", "") for item in content if item.get("text"))
        return _parse_json(text)

    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(invoke)
        try:
            return future.result(timeout=LLM_TIMEOUT_SECONDS)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except Exception as exc:
        logger.warning("finops_llm_call_failed: %s", exc)
        return None


async def llm_judge_data_request(
    agent_key: str,
    context: dict,
    rule_result: dict,
    allowed_targets: list[str],
) -> DataRequest | None:
    if not allowed_targets:
        return None

    prompt = f"""
현재 분석 결과와 지표를 보고 추가 분석이 필요한지 판단하세요.
필요하면 다음 JSON 형식으로만 반환하세요.
필요없으면 null을 반환하세요.

{{
  "target_agent": "허용된 agent_key 중 하나",
  "operation": "수행할 작업",
  "parameters": {{}},
  "required_fields": [],
  "reason": "요청 이유"
}}

허용된 target_agent: {allowed_targets}
허용되지 않은 Agent 요청은 절대 하지 마세요.
AWS를 직접 변경하거나 실행 명령을 내리지 마세요.
반드시 JSON 또는 null만 반환하세요.
"""

    def invoke() -> str:
        from shared.bedrock import ClaudeModel, get_bedrock_client

        client = get_bedrock_client()
        response = client.converse(
            modelId=os.getenv("BEDROCK_MODEL", ClaudeModel.HAIKU.value),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": (
                                f"{prompt}\n\n"
                                f"Agent: {agent_key}\n"
                                f"Context:\n{json.dumps(context, ensure_ascii=False, default=str)}\n\n"
                                f"Rule result:\n{json.dumps(rule_result, ensure_ascii=False, default=str)}"
                            )
                        }
                    ],
                }
            ],
        )
        content = response.get("output", {}).get("message", {}).get("content", [])
        return "\n".join(item.get("text", "") for item in content if item.get("text"))

    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(invoke)
        try:
            text = future.result(timeout=LLM_JUDGE_TIMEOUT_SECONDS).strip()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except Exception as exc:
        logger.warning("finops_llm_judge_data_request_failed: %s", exc)
        return None

    if not text or text.lower() == "null":
        return None
    parsed = _parse_json(text)
    if not parsed:
        return None
    if parsed.get("target_agent") not in allowed_targets:
        return None
    try:
        return DataRequest.model_validate(parsed)
    except Exception as exc:
        logger.warning("finops_llm_judge_data_request_invalid: %s", exc)
        return None


async def handle_broker_request(
    agent_key: str,
    agent_name: str,
    operation: str,
    parameters: dict,
    required_fields: list[str],
    context: dict,
) -> dict | None:
    prompt = f"""
당신은 {agent_name}입니다.
다른 Agent로부터 다음 작업 요청이 왔습니다.

operation: {operation}
parameters: {json.dumps(parameters, ensure_ascii=False, default=str)}
required_fields: {json.dumps(required_fields, ensure_ascii=False, default=str)}

현재 당신의 역할과 보유 데이터로
이 요청을 처리할 수 있는지 판단하세요.

처리 가능하면:
required_fields에 명시된 필드를 모두 채운
JSON 객체만 반환하세요.

처리 불가능하면:
null 을 반환하세요.

처리 불가능한 경우:
- 요청이 당신의 역할 범위를 벗어남
- 필요한 데이터가 없음
- 실행 단계 요청인데 지금은 계획 단계임
  (예: execute, dry_run, scale 등 실행성 operation)

반드시 JSON 또는 null만 반환하세요.
다른 텍스트는 절대 포함하지 마세요.
"""

    def invoke() -> str:
        from shared.bedrock import ClaudeModel, get_bedrock_client

        client = get_bedrock_client()
        response = client.converse(
            modelId=os.getenv("BEDROCK_MODEL", ClaudeModel.HAIKU.value),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": (
                                f"{prompt}\n\n"
                                f"Agent key: {agent_key}\n"
                                f"Context:\n{json.dumps(context, ensure_ascii=False, default=str)}"
                            )
                        }
                    ],
                }
            ],
        )
        content = response.get("output", {}).get("message", {}).get("content", [])
        return "\n".join(item.get("text", "") for item in content if item.get("text"))

    try:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(invoke)
        try:
            text = future.result(timeout=BROKER_REQUEST_TIMEOUT_SECONDS).strip()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except Exception as exc:
        logger.warning("finops_broker_request_handler_failed: %s", exc)
        return None

    if not text or text.lower() == "null":
        return None
    parsed = _parse_json(text)
    if not parsed:
        return None
    missing = [field for field in required_fields if field not in parsed]
    if missing:
        logger.warning(
            "finops_broker_request_handler_missing_fields: agent=%s operation=%s missing=%s",
            agent_key,
            operation,
            missing,
        )
        return None
    return parsed


def standard_response(
    agent_key: str,
    agent_name: str,
    result: dict[str, Any],
    message: str,
    available_results: dict[str, Any],
    reasoning_source: str,
) -> dict[str, Any]:
    evidence = []
    warnings = []
    for source_key, field in AGENT_DEPENDENCIES.get(agent_key, []):
        source_payload = available_results.get(source_key)
        source_result = _response_result(source_payload) if source_payload else {}
        dependency = f"{AGENT_NAMES[source_key]}.{field}"
        if field in source_result:
            evidence.append(f"Used upstream result {dependency}")
        else:
            warnings.append(f"Upstream result {dependency} was not available")

    response = AgentResponse(
        status=AgentStatus.COMPLETED,
        agent_key=agent_key,
        agent_name=agent_name,
        result=result,
        message=message,
        evidence=evidence,
        data_requests=[],
        confidence=AGENT_CONFIDENCE.get(agent_key, 0.75),
        warnings=warnings,
        reasoning_source=reasoning_source,
    )
    return response.model_dump(mode="json")


def get_agent_response(context: dict[str, Any], agent_key: str) -> AgentResponse:
    try:
        payload = context["agent_results"][agent_key]
    except KeyError as exc:
        raise KeyError(f"agent result is not available: {agent_key}") from exc
    return AgentResponse.model_validate(payload)


def get_agent_result(context: dict[str, Any], agent_key: str) -> dict[str, Any]:
    return get_agent_response(context, agent_key).result


def _response_result(payload: Any) -> dict[str, Any]:
    if not payload:
        return {}
    return AgentResponse.model_validate(payload).result


def _parse_json(text: str) -> dict[str, Any] | None:
    payload = text.strip()
    if payload.startswith("```"):
        payload = payload.strip("`").strip()
        if payload.lower().startswith("json"):
            payload = payload[4:].strip()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        start = payload.find("{")
        end = payload.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(payload[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None
