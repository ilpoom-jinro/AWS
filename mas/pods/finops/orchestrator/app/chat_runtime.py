from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
from typing import Any, Callable

from app.chat_tools import (
    get_agent_result,
    get_all_agent_results,
    get_broker_log,
    get_data_collection_issues,
    get_final_report,
    get_plan_candidates,
    get_quality_gate_result,
    get_recommended_candidate,
)
from contracts.models import ReplanIntent


CHAT_SYSTEM_PROMPT = """
당신은 FinOps 보고서 분석 전문가입니다.
주어진 Tool을 사용해 보고서 데이터를 조회하고
근거에 기반한 답변을 제공하세요.

규칙:
- Tool 조회 결과에 없는 내용을 만들어내지 마세요.
- 수치 질문에는 저장된 결과를 그대로 사용하세요.
- 답변에 사용한 데이터 출처(Agent 이름)를 명시하세요.
- Agent 결과에 evidence가 있으면 evidence를 우선 근거로 사용하세요.
- 수치 답변은 가능하면 계산식을 함께 설명하세요.
- source가 fallback 또는 *_signal이면 실시간 수집값이 아닐 수 있음을 구분해서 말하세요.
- Workflow를 변경하거나 실행 명령을 내리지 마세요.
- 한국어로 답변하세요.
"""

CHAT_MAX_TOOL_CALLS = 5
CHAT_TIMEOUT_SECONDS = 30

PLANNER_SYSTEM_PROMPT = """
운영자의 요청을 분석해서 재계획 조건을 JSON으로만 반환하세요.
재계획이 필요없는 질문이면 intent를 "query"로 반환하세요.
직접 AWS를 변경하거나 실행 명령을 내리지 마세요.

replan_from은 다음 중 하나여야 합니다:
business_control, demand_shaping, traffic_forecast,
bottleneck_capacity, infra_execution, cost,
unit_economics, policy_guardrail, observer,
fallback, postmortem_learning

constraints 예시:
  "Pod 최대 15개" -> {"max_pods": 15}
  "비용 40달러 이하" -> {"max_cost_usd": 40}
  "지연 200ms 이하" -> {"max_p95_latency_ms": 200}

forbidden_actions 예시:
  "DB 건드리지 마" -> ["modify_rds"]
  "캐시 변경 없이" -> ["modify_redis"]

조건 변경이 demand_shaping부터 영향받으면 replan_from="demand_shaping"
비용 조건만 바꾸면 replan_from="cost"
반드시 JSON만 반환하세요.
"""

PLANNER_SYSTEM_PROMPT = """
당신은 FinOps 운영 전문가입니다.
운영자의 요청을 분석해서 다음 중 하나로 처리하세요.

[처리 가능한 요청 유형]

1. 특정 Agent만 재실행 (partial_replan)
   예: "Traffic Forecast만 20분 분산으로 다시 계산해줘"
   → intent: "partial_replan"
   → target_agent: "traffic_forecast"
   → constraints: {"push_window_minutes": 20}
   → replan_from: "traffic_forecast"

2. 전체 재계획 (replan)
   예: "Pod 최대 15개로 줄여줘"
   → intent: "replan"
   → replan_from: "demand_shaping"
   → constraints: {"max_pods": 15}

3. 보고서 질의 (query)
   예: "왜 Pod가 22개야?"
   → intent: "query"

4. 이상 상황 설명 요청 (explain)
   예: "지금 왜 이상한거야?"
   → intent: "explain"

처리 가능한 Agent 목록:
  business_control, demand_shaping, traffic_forecast,
  bottleneck_capacity, infra_execution, cost,
  unit_economics, policy_guardrail, observer,
  fallback, postmortem_learning

constraints 예시:
  "Pod 최대 15개" → {"max_pods": 15}
  "비용 40달러 이하" → {"max_cost_usd": 40}
  "지연 200ms 이하" → {"max_p95_latency_ms": 200}
  "20분 분산" → {"push_window_minutes": 20}

forbidden_actions 예시:
  "DB 건드리지 마" → ["modify_rds"]
  "캐시 변경 없이" → ["modify_redis"]

반환 JSON 형식:
{
  "intent": "query|explain|replan|partial_replan",
  "constraints": {},
  "forbidden_actions": [],
  "replan_from": "demand_shaping",
  "target_agent": null,
  "requires_confirmation": false,
  "reason": "해석한 이유"
}

직접 AWS를 변경하거나 실행 명령을 내리지 마세요.
반드시 JSON만 반환하세요.
"""

EXPLAIN_SYSTEM_PROMPT = """
당신은 FinOps 시스템 분석 전문가입니다.
운영자가 현재 상황에 대해 설명을 요청했습니다.

Tool을 사용해서 현재 보고서와 Agent 결과를 조회하고 다음을 설명하세요:

- 어떤 Agent가 어떤 판단을 했는지
- 왜 이 결과가 나왔는지
- 문제가 있다면 어디서 발생했는지
- 해결 방법은 무엇인지
- 설명할 때 Agent 이름, evidence, reasoning_source를 함께 언급하세요.
- evidence가 부족하면 저장된 근거가 부족하다고 명확히 말하세요.

없는 내용을 만들어내지 마세요.
Tool 조회 결과에만 근거해서 설명하세요.
한국어로 답변하세요.
"""

TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "get_final_report": get_final_report,
    "get_agent_result": get_agent_result,
    "get_all_agent_results": get_all_agent_results,
    "get_plan_candidates": get_plan_candidates,
    "get_recommended_candidate": get_recommended_candidate,
    "get_quality_gate_result": get_quality_gate_result,
    "get_broker_log": get_broker_log,
    "get_data_collection_issues": get_data_collection_issues,
}

CHAT_TOOLS = [
    {
        "toolSpec": {
            "name": "get_final_report",
            "description": "Return the full final FinOps report JSON for the current workflow.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "get_agent_result",
            "description": "Return result, evidence, warnings, confidence, and reasoning source for a specific FinOps agent.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "agent_key": {
                            "type": "string",
                            "description": "Agent key such as traffic_forecast, cost, bottleneck_capacity.",
                        }
                    },
                    "required": ["agent_key"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_all_agent_results",
            "description": "Return result, evidence, warnings, confidence, and reasoning source for all FinOps agents in the current workflow.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_plan_candidates",
            "description": "Return the candidate FinOps plans with score, cost, pods, latency, and risk.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "get_recommended_candidate",
            "description": "Return the recommended candidate and the deterministic recommendation reason.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "get_quality_gate_result",
            "description": "Return Quality Gate pass/fail state, issues, and warnings.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "get_broker_log",
            "description": "Return Data Broker call history between agents.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "get_data_collection_issues",
            "description": "Return agents that failed data collection or execution.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
]


def normalize_conversation_history(history: list[dict] | None) -> list[dict[str, str]]:
    normalized = []
    for item in history or []:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            normalized.append({"role": role, "content": content})
    return normalized


def append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)


def should_continue_tool_loop(tool_call_count: int) -> bool:
    return tool_call_count < CHAT_MAX_TOOL_CALLS


def fallback_response(conversation_history: list[dict] | None) -> dict[str, Any]:
    return {
        "answer": "보고서 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.",
        "sources": [],
        "tools_used": [],
        "conversation_history": normalize_conversation_history(conversation_history),
    }


def planner_fallback(reason: str = "파싱 실패로 질의 모드로 전환") -> ReplanIntent:
    return ReplanIntent(
        intent="query",
        constraints={},
        forbidden_actions=[],
        replan_from="demand_shaping",
        requires_confirmation=False,
        reason=reason,
    )


def parse_planner_response(text: str) -> ReplanIntent:
    payload = text.strip()
    if payload.startswith("```"):
        payload = payload.strip("`")
        if payload.lower().startswith("json"):
            payload = payload[4:].strip()
    return ReplanIntent.model_validate(json.loads(payload))


def build_pending_replan_response(
    intent: ReplanIntent,
    conversation_history: list[dict] | None,
    message: str,
) -> dict[str, Any]:
    history = normalize_conversation_history(conversation_history)
    history.append({"role": "user", "content": message})
    answer = f"{intent.reason} 확인하시겠습니까?"
    if intent.intent == "partial_replan" and intent.target_agent:
        answer = f"{intent.target_agent}를 새 조건으로 재실행하겠습니다. 확인하시겠습니까?"
    else:
        answer = f"{intent.reason} 확인하시겠습니까?"
    history.append({"role": "assistant", "content": answer})
    return {
        "answer": answer,
        "pending_replan": intent.model_dump(mode="json"),
        "sources": [],
        "tools_used": ["run_planner_llm"],
        "conversation_history": history,
    }


def _to_bedrock_messages(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {"role": item["role"], "content": [{"text": item["content"]}]}
        for item in history
        if item["role"] in {"user", "assistant"}
    ]


def _invoke_tool(conn, workflow_id: str, name: str, args: dict[str, Any]) -> Any:
    tool = TOOL_FUNCTIONS.get(name)
    if tool is None:
        return {"error": f"unknown tool: {name}"}
    if name == "get_agent_result":
        return tool(conn, workflow_id, args.get("agent_key", ""))
    return tool(conn, workflow_id)


def _extract_text(content: list[dict[str, Any]]) -> str:
    return "\n".join(block.get("text", "") for block in content if block.get("text")).strip()


def _extract_tool_uses(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [block["toolUse"] for block in content if isinstance(block.get("toolUse"), dict)]


async def _converse_with_timeout(
    client: Any,
    *,
    model_id: str,
    messages: list[dict[str, Any]],
    system_prompt: str = CHAT_SYSTEM_PROMPT,
) -> dict[str, Any]:
    def invoke() -> dict[str, Any]:
        return client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=messages,
            toolConfig={"tools": CHAT_TOOLS},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(executor, invoke),
            timeout=CHAT_TIMEOUT_SECONDS,
        )


async def _planner_converse_with_timeout(
    client: Any,
    *,
    model_id: str,
    message: str,
    current_plan: dict[str, Any],
) -> dict[str, Any]:
    def invoke() -> dict[str, Any]:
        return client.converse(
            modelId=model_id,
            system=[{"text": PLANNER_SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": (
                                f"요청: {message}\n\n"
                                f"현재 계획:\n{json.dumps(current_plan, ensure_ascii=False, default=str)}"
                            )
                        }
                    ],
                }
            ],
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(executor, invoke),
            timeout=CHAT_TIMEOUT_SECONDS,
        )


async def run_planner_llm(
    conn,
    workflow_id: str,
    message: str,
    current_plan: dict,
) -> ReplanIntent:
    try:
        from shared.bedrock import ClaudeModel, get_bedrock_client

        client = get_bedrock_client()
        model_id = os.getenv("BEDROCK_MODEL", ClaudeModel.HAIKU.value)
        response = await _planner_converse_with_timeout(
            client,
            model_id=model_id,
            message=message,
            current_plan=current_plan,
        )
        content = response.get("output", {}).get("message", {}).get("content", [])
        text = _extract_text(content)
        return parse_planner_response(text)
    except Exception:
        return planner_fallback()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(executor, invoke),
            timeout=CHAT_TIMEOUT_SECONDS,
        )


async def run_report_chat(
    conn,
    workflow_id: str,
    message: str,
    conversation_history: list[dict],
) -> dict[str, Any]:
    history = normalize_conversation_history(conversation_history)
    history.append({"role": "user", "content": message})
    sources: list[str] = []
    tools_used: list[str] = []

    try:
        from shared.bedrock import ClaudeModel, get_bedrock_client

        client = get_bedrock_client()
        model_id = os.getenv("BEDROCK_MODEL", ClaudeModel.HAIKU.value)
        bedrock_messages = _to_bedrock_messages(history)
        tool_call_count = 0

        while True:
            response = await _converse_with_timeout(
                client,
                model_id=model_id,
                messages=bedrock_messages,
            )
            output_message = response.get("output", {}).get("message", {})
            content = output_message.get("content", [])
            tool_uses = _extract_tool_uses(content)
            if not tool_uses:
                answer = _extract_text(content) or "보고서에서 답변에 필요한 근거를 찾지 못했습니다."
                history.append({"role": "assistant", "content": answer})
                return {
                    "answer": answer,
                    "sources": sources,
                    "tools_used": tools_used,
                    "conversation_history": history,
                }

            bedrock_messages.append({"role": "assistant", "content": content})
            tool_results = []
            for tool_use in tool_uses:
                if not should_continue_tool_loop(tool_call_count):
                    break
                tool_call_count += 1
                name = tool_use.get("name", "")
                args = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
                append_unique(tools_used, name)
                if name == "get_agent_result":
                    append_unique(sources, args.get("agent_key"))
                result = _invoke_tool(conn, workflow_id, name, args)
                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use["toolUseId"],
                            "content": [{"json": result}],
                            "status": "success",
                        }
                    }
                )
            if not tool_results:
                answer = "보고서 조회 Tool 호출 한도에 도달했습니다. 질문 범위를 조금 좁혀 다시 요청해주세요."
                history.append({"role": "assistant", "content": answer})
                return {
                    "answer": answer,
                    "sources": sources,
                    "tools_used": tools_used,
                    "conversation_history": history,
                }
            bedrock_messages.append({"role": "user", "content": tool_results})
    except Exception:
        return fallback_response(history)


async def run_explain_llm(
    conn,
    workflow_id: str,
    message: str,
    conversation_history: list[dict],
) -> dict[str, Any]:
    history = normalize_conversation_history(conversation_history)
    history.append({"role": "user", "content": message})
    sources: list[str] = []
    tools_used: list[str] = []

    try:
        from shared.bedrock import ClaudeModel, get_bedrock_client

        client = get_bedrock_client()
        model_id = os.getenv("BEDROCK_MODEL", ClaudeModel.HAIKU.value)
        bedrock_messages = _to_bedrock_messages(history)
        tool_call_count = 0

        while True:
            response = await _converse_with_timeout(
                client,
                model_id=model_id,
                messages=bedrock_messages,
                system_prompt=EXPLAIN_SYSTEM_PROMPT,
            )
            output_message = response.get("output", {}).get("message", {})
            content = output_message.get("content", [])
            tool_uses = _extract_tool_uses(content)
            if not tool_uses:
                answer = _extract_text(content) or "현재 상황을 설명할 충분한 보고서 근거를 찾지 못했습니다."
                history.append({"role": "assistant", "content": answer})
                return {
                    "answer": answer,
                    "sources": sources,
                    "tools_used": tools_used,
                    "conversation_history": history,
                }

            bedrock_messages.append({"role": "assistant", "content": content})
            tool_results = []
            for tool_use in tool_uses:
                if not should_continue_tool_loop(tool_call_count):
                    break
                tool_call_count += 1
                name = tool_use.get("name", "")
                args = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
                append_unique(tools_used, name)
                if name == "get_agent_result":
                    append_unique(sources, args.get("agent_key"))
                elif name == "get_all_agent_results":
                    append_unique(sources, "all_agents")
                result = _invoke_tool(conn, workflow_id, name, args)
                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use["toolUseId"],
                            "content": [{"json": result}],
                            "status": "success",
                        }
                    }
                )
            if not tool_results:
                answer = "상황 설명에 필요한 보고서 조회 Tool 호출을 완료하지 못했습니다."
                history.append({"role": "assistant", "content": answer})
                return {
                    "answer": answer,
                    "sources": sources,
                    "tools_used": tools_used,
                    "conversation_history": history,
                }
            bedrock_messages.append({"role": "user", "content": tool_results})
    except Exception:
        return fallback_response(history)
