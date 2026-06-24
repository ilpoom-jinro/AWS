from __future__ import annotations

import json
from typing import Any

from contracts.models import AgentResponse, AgentStatus, DataRequest, PlanCandidate


BROKER_MAX_DEPTH = 3
BROKER_MAX_AGENT_CALLS = 2
BROKER_MAX_TOTAL_CALLS = 30
DEFAULT_CANDIDATE_WEIGHTS = {
    "availability": 0.5,
    "cost": 0.3,
    "latency": 0.2,
}


AGENT_SEQUENCE = [
    ("business_control", "Business Control Agent"),
    ("demand_shaping", "Demand Shaping Agent"),
    ("traffic_forecast", "Traffic Forecast Agent"),
    ("bottleneck_capacity", "Bottleneck Capacity Agent"),
    ("infra_execution", "Infra Execution Planner"),
    ("cost", "Cost Agent"),
    ("unit_economics", "Unit Economics Agent"),
    ("policy_guardrail", "Policy Guardrail Agent"),
    ("observer", "Observer Agent"),
    ("fallback", "Fallback Planner"),
    ("postmortem_learning", "Postmortem Learning Agent"),
]

AGENT_TASK_QUEUES = {
    key: f"finops-{key.replace('_', '-')}-agent-task-queue"
    for key, _ in AGENT_SEQUENCE
}


def broker_failure(reason: str, message: str) -> dict[str, Any]:
    return {
        "_broker_status": "failed",
        "_broker_reason": reason,
        "_broker_message": message,
    }


def broker_cache_key(request: DataRequest) -> str:
    parameters = json.dumps(
        request.parameters,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"{request.target_agent}:{request.operation}:{parameters}"


def get_broker_cached_result(
    context: dict[str, Any],
    request: DataRequest,
) -> dict[str, Any] | None:
    return context["broker_cache"].get(broker_cache_key(request))


def broker_guard_failure(
    context: dict[str, Any],
    target_agent: str,
    call_stack: list[str],
) -> dict[str, Any] | None:
    if context["broker_total_calls"] >= BROKER_MAX_TOTAL_CALLS:
        return broker_failure(
            "total_call_limit",
            f"Broker call limit {BROKER_MAX_TOTAL_CALLS} was reached",
        )
    if len(call_stack) >= BROKER_MAX_DEPTH:
        return broker_failure(
            "max_depth",
            f"Broker call depth {BROKER_MAX_DEPTH} was reached: {call_stack}",
        )
    if target_agent in call_stack:
        return broker_failure(
            "cycle_detected",
            f"Agent {target_agent} is already in the call stack: {call_stack}",
        )
    calls = context["broker_agent_calls"].get(target_agent, 0)
    if calls >= BROKER_MAX_AGENT_CALLS:
        return broker_failure(
            "agent_call_limit",
            f"Agent {target_agent} call limit {BROKER_MAX_AGENT_CALLS} was reached",
        )
    return None


def extract_required_fields(
    response: AgentResponse,
    required_fields: list[str],
) -> dict[str, Any]:
    missing = [field for field in required_fields if field not in response.result]
    if missing:
        return broker_failure(
            "missing_required_fields",
            f"Agent {response.agent_key} did not return required fields: {missing}",
        )
    return {
        "_broker_status": "completed",
        **{field: response.result[field] for field in required_fields},
    }


def _request(
    source_key: str,
    field: str,
    label: str,
    reason: str,
) -> dict[str, str]:
    return {
        "source_key": source_key,
        "source_name": dict(AGENT_SEQUENCE)[source_key],
        "field": field,
        "label": label,
        "reason": reason,
    }


AGENT_DATA_REQUESTS = {
    "demand_shaping": [
        _request("business_control", "max_delay_minutes", "allowed delay", "Build the send window."),
    ],
    "traffic_forecast": [
        _request("demand_shaping", "peak_reduction_percent", "peak reduction", "Forecast shaped RPS."),
        _request("business_control", "target_users", "target audience", "Size the event demand."),
    ],
    "bottleneck_capacity": [
        _request("traffic_forecast", "peak_rps_after", "forecast RPS", "Validate downstream capacity."),
    ],
    "infra_execution": [
        _request("traffic_forecast", "required_app_pods", "required pods", "Create the scale plan."),
    ],
    "cost": [
        _request("infra_execution", "target_app_pods", "target pods", "Estimate incremental cost."),
    ],
    "unit_economics": [
        _request("cost", "total", "estimated cost", "Compare cost with expected value."),
    ],
    "policy_guardrail": [
        _request("unit_economics", "cost_ratio", "cost-to-value ratio", "Validate policy and approval."),
    ],
    "observer": [
        _request("traffic_forecast", "peak_rps_after", "forecast RPS", "Set monitoring thresholds."),
        _request("policy_guardrail", "approval_required", "approval requirement", "Gate operations."),
    ],
    "fallback": [
        _request("policy_guardrail", "allowed", "allowed actions", "Exclude prohibited fallback actions."),
    ],
    "postmortem_learning": [
        _request("traffic_forecast", "peak_rps_before", "forecast baseline", "Compare forecast and actual."),
        _request("cost", "total", "forecast cost", "Compare estimated and actual cost."),
    ],
}


def get_agent_response(context: dict[str, Any], agent_key: str) -> AgentResponse:
    return AgentResponse.model_validate(context["agent_results"][agent_key])


def get_agent_result(context: dict[str, Any], agent_key: str) -> dict[str, Any]:
    return get_agent_response(context, agent_key).result


def get_agent_result_or_empty(
    context: dict[str, Any],
    agent_key: str,
) -> dict[str, Any]:
    if agent_key not in context.get("agent_results", {}):
        return {}
    return get_agent_result(context, agent_key)


def _lower_is_better_score(value: float, limit: float) -> float:
    if limit <= 0:
        return 1.0 if value <= 0 else 0.0
    return max(0.0, min(1.0, 1.0 - value / limit))


def score_candidate(
    candidate: PlanCandidate,
    weights: dict[str, float],
    constraints: dict[str, float],
) -> float:
    if candidate.budget_exceeded or candidate.policy_violations:
        return 0.0
    availability = _lower_is_better_score(
        float(candidate.required_pods),
        float(constraints["max_pods"]),
    )
    cost = _lower_is_better_score(
        candidate.estimated_cost_usd,
        float(constraints["max_cost_usd"]),
    )
    latency = _lower_is_better_score(
        candidate.estimated_p95_ms,
        float(constraints["max_p95_ms"]),
    )
    return round(
        weights["availability"] * availability
        + weights["cost"] * cost
        + weights["latency"] * latency,
        6,
    )


def build_plan_candidates(
    context: dict[str, Any],
    shaping: dict[str, Any],
    forecast: dict[str, Any],
    cost: dict[str, Any],
    policy: dict[str, Any],
    infra: dict[str, Any],
) -> tuple[list[PlanCandidate], PlanCandidate | None, float]:
    budget = float(
        cost.get(
            "event_incremental_budget_usd",
            cost.get("estimated_cost_usd", cost.get("total", 0.0)),
        )
    )
    max_p95 = float(context.get("constraints", {}).get("max_p95_ms", 200.0))
    policy_blocked = policy.get("allowed") is False or policy.get("proceed") is False
    policy_violations = ["policy_guardrail_blocked"] if policy_blocked else []
    forecast_by_label = {
        item["label"]: item for item in forecast.get("candidate_forecasts", [])
    }
    cost_by_label = {
        item["label"]: item for item in cost.get("candidate_costs", [])
    }

    candidates: list[PlanCandidate] = []
    for shaping_candidate in shaping.get("candidates", []):
        label = shaping_candidate["label"]
        forecast_candidate = forecast_by_label.get(label)
        cost_candidate = cost_by_label.get(label)
        if not forecast_candidate or not cost_candidate:
            continue
        budget_exceeded = bool(cost_candidate["budget_exceeded"])
        estimated_p95 = float(forecast_candidate["estimated_p95_ms"])
        risk_level = "low" if label == "안정성 우선" else "medium"
        if budget_exceeded or policy_violations or estimated_p95 > max_p95:
            risk_level = "high"
        candidates.append(
            PlanCandidate(
                label=label,
                push_window_minutes=int(shaping_candidate["push_window_minutes"]),
                required_pods=int(forecast_candidate["required_app_pods"]),
                estimated_cost_usd=float(cost_candidate["estimated_cost_usd"]),
                estimated_p95_ms=estimated_p95,
                risk_level=risk_level,
                budget_exceeded=budget_exceeded,
                policy_violations=list(policy_violations),
            )
        )

    if (
        not candidates
        and forecast.get("required_app_pods") is not None
        and (
            cost.get("estimated_cost_usd") is not None
            or cost.get("total") is not None
        )
    ):
        estimated_cost = float(cost.get("estimated_cost_usd", cost.get("total", 0.0)))
        estimated_p95 = float(forecast.get("p95_latency_ms") or 0.0)
        budget_exceeded = bool(
            cost.get("budget_exceeded", estimated_cost > budget)
        )
        risk_level = "high" if (
            budget_exceeded or policy_violations or estimated_p95 > max_p95
        ) else "medium"
        candidates.append(
            PlanCandidate(
                label="기본 계획",
                push_window_minutes=int(
                    shaping.get(
                        "send_window_minutes",
                        context["policy"]["max_general_delay_minutes"],
                    )
                ),
                required_pods=int(forecast["required_app_pods"]),
                estimated_cost_usd=estimated_cost,
                estimated_p95_ms=estimated_p95,
                risk_level=risk_level,
                budget_exceeded=budget_exceeded,
                policy_violations=list(policy_violations),
            )
        )

    if not candidates:
        return [], None, budget

    max_candidate_pods = max(candidate.required_pods for candidate in candidates)
    constraints = {
        "max_pods": float(
            context.get("constraints", {}).get("max_pods")
            or infra.get("nodegroup_max")
            or max_candidate_pods * 1.25
        ),
        "max_cost_usd": float(
            context.get("constraints", {}).get("max_cost_usd") or budget
        ),
        "max_p95_ms": max_p95,
    }
    weights = {
        **DEFAULT_CANDIDATE_WEIGHTS,
        **context.get("candidate_weights", {}),
    }
    scored = [
        candidate.model_copy(
            update={"score": score_candidate(candidate, weights, constraints)}
        )
        for candidate in candidates
    ]
    scored.sort(key=lambda item: item.score, reverse=True)
    recommended = next((candidate for candidate in scored if candidate.score > 0), None)
    return scored, recommended, budget


def evaluate_quality_gate(
    context: dict[str, Any],
    candidates: list[PlanCandidate],
    recommended: PlanCandidate | None,
    budget: float,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    expected_agents = [key for key, _ in AGENT_SEQUENCE]
    responses = {
        key: get_agent_response(context, key)
        for key in expected_agents
        if key in context.get("agent_results", {})
    }
    missing_agents = [key for key in expected_agents if key not in responses]
    if missing_agents:
        issues.append(f"missing_agents:{','.join(missing_agents)}")

    blocked_agents = [
        key for key, response in responses.items()
        if response.status == AgentStatus.BLOCKED
    ]
    failed_agents = [
        key for key, response in responses.items()
        if response.status == AgentStatus.FAILED
    ]
    review_agents = [
        key for key, response in responses.items()
        if response.status == AgentStatus.REQUIRES_REVIEW
    ]
    low_confidence_agents = [
        key for key, response in responses.items() if response.confidence < 0.5
    ]
    if blocked_agents:
        issues.append(f"has_blocked_agents:{','.join(blocked_agents)}")
    if failed_agents:
        issues.append(f"has_failed_agents:{','.join(failed_agents)}")
    if len(low_confidence_agents) >= 3:
        issues.append(f"low_confidence:{','.join(low_confidence_agents)}")
    if review_agents:
        warnings.append(f"requires_review_agents:{','.join(review_agents)}")

    policy = (
        get_agent_result(context, "policy_guardrail")
        if "policy_guardrail" in responses
        else {}
    )
    if policy.get("allowed") is False or policy.get("proceed") is False:
        issues.append("policy_blocked")
    if recommended is None:
        issues.append("no_valid_candidate")
    elif recommended.estimated_cost_usd > budget:
        issues.append("budget_exceeded")

    zero_score_candidates = [candidate.label for candidate in candidates if candidate.score == 0]
    if zero_score_candidates:
        warnings.append(f"zero_score_candidates:{','.join(zero_score_candidates)}")
    non_recommended_budget_exceeded = [
        candidate.label
        for candidate in candidates
        if candidate.budget_exceeded
        and (recommended is None or candidate.label != recommended.label)
    ]
    if non_recommended_budget_exceeded:
        warnings.append(
            "non_recommended_budget_exceeded:"
            + ",".join(non_recommended_budget_exceeded)
        )

    return {
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
    }, failed_agents


def plan_status(plan: dict[str, Any]) -> str:
    return "plan_ready" if plan["quality_gate_result"]["passed"] else "requires_review"


def build_final_plan(context: dict[str, Any]) -> dict[str, Any]:
    shaping = get_agent_result_or_empty(context, "demand_shaping")
    forecast = get_agent_result_or_empty(context, "traffic_forecast")
    cost = get_agent_result_or_empty(context, "cost")
    policy = get_agent_result_or_empty(context, "policy_guardrail")
    infra = get_agent_result_or_empty(context, "infra_execution")
    bottleneck = get_agent_result_or_empty(context, "bottleneck_capacity")
    observer = get_agent_result_or_empty(context, "observer")
    fallback = get_agent_result_or_empty(context, "fallback")
    postmortem = get_agent_result_or_empty(context, "postmortem_learning")
    data_sources = {
        "business": context.get("business", {}).get("calendar_source", "business_calendar"),
        "traffic": forecast.get("source", "traffic_observability_signal"),
        "infra": infra.get("source", "infra_capacity_signal"),
        "cost": cost.get("source", "cost_signal"),
        "policy": context.get("policy_source", {}).get("policy_version", "business_policy"),
    }
    candidates, recommended, budget = build_plan_candidates(
        context,
        shaping,
        forecast,
        cost,
        policy,
        infra,
    )
    quality_gate, data_collection_issues = evaluate_quality_gate(
        context,
        candidates,
        recommended,
        budget,
    )
    recommendation_reason = (
        (
            f"비용 ${recommended.estimated_cost_usd:.2f}로 예산 내 유지, "
            f"p95 {recommended.estimated_p95_ms:g}ms 예상, "
            f"Pod {recommended.required_pods}개로 안정성 확보"
        )
        if recommended
        else "품질 조건을 충족하는 유효한 후보가 없습니다."
    )
    return {
        "event_id": context["event"]["event_id"],
        "peak_rps_before": forecast.get("peak_rps_before"),
        "peak_rps_after": forecast.get("peak_rps_after"),
        "required_app_pods": forecast.get("required_app_pods"),
        "estimated_cost_usd": cost.get("total"),
        "approval_required": policy.get("approval_required"),
        "execution_mode": "dry_run",
        "plan_candidates": [
            candidate.model_dump(mode="json") for candidate in candidates
        ],
        "recommended_candidate": (
            recommended.model_dump(mode="json") if recommended else None
        ),
        "recommendation_reason": recommendation_reason,
        "quality_gate_result": quality_gate,
        "data_collection_issues": data_collection_issues,
        "data_sources": data_sources,
        "report": {
            "title": "FinOps Event Readiness Report",
            "event": {
                "event_id": context["event"]["event_id"],
                "title": context["event"]["title"],
                "grade": context["event"]["grade"],
                "target_users": context["event"]["target_users"],
                "scheduled_at": context["event"]["scheduled_at"],
            },
            "executive_summary": (
                f"Peak RPS is expected to move from {forecast.get('peak_rps_before')} to "
                f"{forecast.get('peak_rps_after')} after demand shaping. Prepare "
                f"{forecast.get('required_app_pods')} app pods in dry-run mode. "
                f"Estimated incremental cost is ${cost.get('total')}."
            ),
            "data_collection": {
                "sources": data_sources,
                "live_command_success_count": "see agent decision payloads",
                "failed_collectors": "see agent decision payloads",
            },
            "traffic": {
                "peak_rps_before": forecast.get("peak_rps_before"),
                "peak_rps_after": forecast.get("peak_rps_after"),
                "required_app_pods": forecast.get("required_app_pods"),
                "queue_depth": forecast.get("queue_depth"),
                "p95_latency_ms": forecast.get("p95_latency_ms"),
            },
            "capacity": {
                "target_app_pods": infra.get("target_app_pods"),
                "current_app_pods": infra.get("current_app_pods"),
                "ready_app_pods": infra.get("ready_app_pods"),
                "bottleneck_status": bottleneck.get("status"),
                "rds_cpu": bottleneck.get("db_cpu"),
                "cache_hit_ratio": bottleneck.get("cache_hit_ratio"),
                "spot_candidates": infra.get("spot_instance_types", []),
                "spot_placement_scores": infra.get("spot_placement_scores", []),
            },
            "cost": {
                "estimated_event_cost_usd": cost.get("total"),
                "month_to_date_usd": cost.get("cost_explorer_month_to_date_usd"),
                "cur_month_to_date_usd": cost.get("cur_month_to_date_usd"),
                "projected_monthly_usd": cost.get("cur_projected_monthly_usd"),
                "event_budget_usd": cost.get("event_incremental_budget_usd"),
            },
            "policy": {
                "approval_required": policy.get("approval_required"),
                "allowed_actions": policy.get("allowed", []),
                "forbidden_actions": policy.get("forbidden", []),
                "policy_version": policy.get("policy_version"),
            },
            "operations": {
                "scale_out_at": infra.get("scale_out_at"),
                "prewarm_at": infra.get("prewarm_at"),
                "scale_down": infra.get("scale_down"),
                "observer_recommendation": observer.get("recommendation"),
                "fallback": fallback,
                "postmortem": postmortem,
            },
            "candidate_comparison": [
                candidate.model_dump(mode="json") for candidate in candidates
            ],
        },
        "recommended_actions": [
            "Send VIP notifications immediately",
            f"Spread general notifications over {context['policy']['max_general_delay_minutes']} minutes",
            "Prewarm CDN and cache 15 minutes before the event",
            "Scale out for forecast peak and scale down from observed RPS",
        ],
    }
