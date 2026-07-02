from __future__ import annotations

import concurrent.futures
import json
import logging
import os
from pathlib import Path
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

AGENT_CAPABILITIES: dict[str, dict[str, Any]] = {
    "business_control": {
        "operations": [
            "classify_event",
            "validate_event",
        ],
        "fields": {
            "event_id": ["result.event_id"],
            "grade": ["result.grade"],
            "target_users": ["result.target_users"],
            "vip_audience_count": ["result.vip_audience_count"],
            "general_audience_count": ["result.general_audience_count"],
            "push_channel": ["result.push_channel"],
            "campaign_importance": ["result.campaign_importance"],
            "approval_required": ["result.approval_required"],
            "max_delay_minutes": ["result.max_delay_minutes"],
        },
    },
    "demand_shaping": {
        "operations": [
            "reshape",
            "recalculate_window",
        ],
        "fields": {
            "send_window_minutes": ["result.send_window_minutes"],
            "peak_reduction_percent": ["result.peak_reduction_percent"],
            "vip_send_mode": ["result.vip_send_mode"],
            "general_send_mode": ["result.general_send_mode"],
            "candidates": ["result.candidates"],
        },
    },
    "traffic_forecast": {
        "operations": [
            "reforecast",
            "reforecast_with_updated_constraints",
            "reforecast_with_demand_shaping_update",
            "validate_forecast",
        ],
        "fields": {
            "peak_rps_after": [
                "result.peak_rps_after",
                "candidate_forecasts[0].peak_rps_after",
            ],
            "required_app_pods": [
                "result.required_app_pods",
                "candidate_forecasts[0].required_app_pods",
            ],
            "estimated_p95_ms": [
                "candidate_forecasts[0].estimated_p95_ms",
                "result.p95_latency_ms",
            ],
            "adjusted_capacity_rps": [
                "result.adjusted_capacity_rps",
            ],
            "p95_latency_ms": [
                "result.p95_latency_ms",
                "candidate_forecasts[0].estimated_p95_ms",
            ],
            "peak_rps_before": ["result.peak_rps_before"],
            "send_window_minutes": ["result.send_window_minutes"],
            "peak_reduction_percent": ["result.peak_reduction_percent"],
            "candidate_forecasts": ["result.candidate_forecasts"],
            "pod_scaling_timeline": ["result.pod_scaling_timeline"],
            "risk_assessment": ["result.risk_assessment"],
            "reforecast": ["result.reforecast"],
        },
    },
    "bottleneck_capacity": {
        "operations": [
            "validate_capacity",
            "check_bottleneck",
        ],
        "fields": {
            "db_cpu": ["result.db_cpu"],
            "rds_connections": ["result.rds_connections"],
            "rds_read_iops": ["result.rds_read_iops"],
            "cache_hit_ratio": ["result.cache_hit_ratio"],
            "validated_rps": ["result.validated_rps"],
            "required_app_pods": ["result.required_app_pods"],
            "bottleneck_risk": ["result.bottleneck_risk"],
            "status": ["result.status"],
            "reforecast_applied": ["result.reforecast_applied"],
            "adjusted_capacity_rps": ["result.adjusted_capacity_rps"],
            "pod_scaling_timeline": ["result.pod_scaling_timeline"],
        },
    },
    "infra_execution": {
        "operations": [
            "validate_capacity_plan",
            "get_target_pods",
        ],
        "fields": {
            "target_app_pods": ["result.target_app_pods"],
            "scale_out_at": ["result.scale_out_at"],
            "prewarm_at": ["result.prewarm_at"],
            "scale_down": ["result.scale_down"],
            "current_app_pods": ["result.current_app_pods"],
            "ready_app_pods": ["result.ready_app_pods"],
            "nodegroup_desired": ["result.nodegroup_desired"],
            "nodegroup_max": ["result.nodegroup_max"],
        },
    },
    "unit_economics": {
        "operations": [
            "recalculate",
            "validate_cost_value_alignment",
        ],
        "fields": {
            "cost_ratio": ["result.cost_ratio"],
            "estimated_cost_usd": ["result.estimated_cost_usd"],
            "expected_value_usd": ["result.expected_value_usd"],
            "override": ["result.override"],
        },
    },
    "policy_guardrail": {
        "operations": [
            "validate_policy",
            "validate_cost_value_alignment",
        ],
        "fields": {
            "allowed": ["result.allowed"],
            "forbidden": ["result.forbidden"],
            "approval_required": ["result.approval_required"],
            "cost_ratio": ["result.cost_ratio"],
            "monthly_budget_limit_usd": ["result.monthly_budget_limit_usd"],
            "approval_required_over_usd": ["result.approval_required_over_usd"],
            "policy_version": ["result.policy_version"],
            "proceed": ["result.proceed"],
        },
    },
    "cost": {
        "operations": [
            "estimate_candidate",
            "recalculate",
        ],
        "fields": {
            "total": ["result.total"],
            "estimated_cost_usd": ["result.estimated_cost_usd"],
            "budget_exceeded": ["result.budget_exceeded"],
            "pod_count": ["result.pod_count"],
            "event_incremental_budget_usd": ["result.event_incremental_budget_usd"],
            "candidate_costs": ["result.candidate_costs"],
        },
    },
    "observer": {
        "operations": [
            "generate_monitoring_plan",
        ],
        "fields": {
            "mode": ["result.mode"],
            "watch": ["result.watch"],
            "recommendation": ["result.recommendation"],
            "forecast_peak_rps": ["result.forecast_peak_rps"],
            "forecast_required_pods": ["result.forecast_required_pods"],
            "forecast_p95_ms": ["result.forecast_p95_ms"],
            "approval_required": ["result.approval_required"],
            "scale_down_rps_threshold": ["result.scale_down_rps_threshold"],
            "alert_rps_threshold": ["result.alert_rps_threshold"],
            "monitoring_interval_seconds": ["result.monitoring_interval_seconds"],
        },
    },
    "fallback": {
        "operations": [
            "generate_fallback_plan",
        ],
        "fields": {
            "vip_only": ["result.vip_only"],
            "general_hold": ["result.general_hold"],
            "static_report": ["result.static_report"],
            "allowed_actions": ["result.allowed_actions"],
            "excluded_actions": ["result.excluded_actions"],
        },
    },
    "postmortem_learning": {
        "operations": [
            "prepare_learning",
        ],
        "fields": {
            "profile_update": ["result.profile_update"],
            "compare": ["result.compare"],
            "forecast_peak_rps": ["result.forecast_peak_rps"],
            "forecast_cost_usd": ["result.forecast_cost_usd"],
        },
    },
}


def load_capability_md(agent_key: str) -> str:
    agent_dir_map = {
        "traffic_forecast": "traffic-forecast",
        "bottleneck_capacity": "bottleneck-capacity",
        "infra_execution": "infra-execution",
        "unit_economics": "unit-economics",
        "policy_guardrail": "policy-guardrail",
        "postmortem_learning": "postmortem-learning",
        "business_control": "business-control",
        "demand_shaping": "demand-shaping",
    }
    dir_name = agent_dir_map.get(agent_key, agent_key)
    capability_path = Path(__file__).resolve().parents[2] / dir_name / "capability.md"
    if capability_path.exists():
        return capability_path.read_text(encoding="utf-8")
    return ""


def resolve_fields_from_context(
    agent_key: str,
    required_fields: list[str],
    agent_result: dict,
) -> dict[str, Any]:
    field_map = AGENT_CAPABILITIES.get(agent_key, {}).get("fields", {})
    resolved: dict[str, Any] = {}
    for field in required_fields:
        for field_path in field_map.get(field, []):
            value = _resolve_field_path(agent_result, field_path)
            if value is not None:
                resolved[field] = value
                break
    return resolved


def build_agent_capability_field_summary(target_agents: list[str]) -> str:
    lines: list[str] = []
    for target_agent in target_agents:
        fields = sorted(AGENT_CAPABILITIES.get(target_agent, {}).get("fields", {}))
        if fields:
            lines.append(
                f"  {target_agent}:\n"
                f"    반환 가능 필드: {', '.join(fields)}"
            )
        else:
            lines.append(
                f"  {target_agent}:\n"
                "    반환 가능 필드: capability 미등록 - 기존 요청 필드만 사용"
            )
    return "\n".join(lines)


def filter_required_fields_by_capability(
    target_agent: str,
    required_fields: list[str],
) -> list[str]:
    capability = AGENT_CAPABILITIES.get(target_agent)
    if not capability:
        return list(required_fields)

    allowed_fields = set(capability.get("fields", {}).keys())
    return [field for field in required_fields if field in allowed_fields]


def _resolve_field_path(agent_result: dict, field_path: str) -> Any:
    if field_path.startswith("result."):
        field_path = field_path.removeprefix("result.")

    current: Any = agent_result
    for part in field_path.split("."):
        if part.endswith("[0]"):
            key = part[:-3]
            if not isinstance(current, dict):
                return None
            current = current.get(key)
            if not isinstance(current, list) or not current:
                return None
            current = current[0]
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def call_llm(prompt: str, context_data: dict[str, Any]) -> dict[str, Any] | None:
    # DEPRECATED:
    # Agent-internal rule-result correction by LLM is intentionally disabled.
    # Keep this symbol for import compatibility; llm_judge_data_request() and
    # handle_broker_request() remain the only Agent-side LLM paths.
    return None


async def llm_judge_data_request(
    agent_key: str,
    context: dict,
    rule_result: dict,
    allowed_targets: list[str],
) -> DataRequest | None:
    if not allowed_targets:
        return None

    capability_summary = build_agent_capability_field_summary(allowed_targets)
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

    prompt += f"""

요청 가능한 target Agent와 반환 가능한 필드:

{capability_summary}

required_fields는 반드시 위 목록 안에서만 선택하세요.
목록에 없는 필드는 요청하지 마세요.
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
    target_agent = parsed.get("target_agent")
    if target_agent not in allowed_targets:
        return None
    required_fields = parsed.get("required_fields")
    if not isinstance(required_fields, list):
        return None
    filtered_fields = filter_required_fields_by_capability(
        str(target_agent),
        [field for field in required_fields if isinstance(field, str)],
    )
    if not filtered_fields:
        logger.info(
            "finops_llm_judge_data_request_no_supported_fields: agent=%s target=%s requested=%s",
            agent_key,
            target_agent,
            required_fields,
        )
        return None
    parsed["required_fields"] = filtered_fields
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
    capability = AGENT_CAPABILITIES.get(agent_key)
    agent_result = (
        context.get("agent_results", {})
        .get(agent_key, {})
        .get("result", {})
    )
    resolved_fields: dict[str, Any] = {}
    if capability:
        if operation not in capability.get("operations", []):
            logger.info(
                "finops_broker_request_operation_not_allowed: agent=%s operation=%s",
                agent_key,
                operation,
            )
            return None
        resolved_fields = resolve_fields_from_context(
            agent_key,
            required_fields,
            agent_result,
        )
        if all(field in resolved_fields for field in required_fields):
            return resolved_fields

    missing_fields = [
        field for field in required_fields if field not in resolved_fields
    ]
    capability_text = load_capability_md(agent_key)
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
                                f"Capability:\n{capability_text}\n\n"
                                f"Resolved fields:\n{json.dumps(resolved_fields, ensure_ascii=False, default=str)}\n\n"
                                f"Missing fields:\n{json.dumps(missing_fields, ensure_ascii=False, default=str)}\n\n"
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
    parsed = {**resolved_fields, **parsed}
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
