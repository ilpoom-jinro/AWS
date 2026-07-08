from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "unit_economics"
AGENT_NAME = "Unit Economics Agent"
LLM_PROMPT = None


def _context_number(context: dict[str, Any], key: str, default: float) -> float:
    value = context.get(key)
    if value is None:
        value = context.get("signals", {}).get(key)
    if value is None:
        value = context.get("infra", {}).get(key)
    if value is None:
        value = context.get("cost_source", {}).get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _context_text(context: dict[str, Any], key: str, default: str) -> str:
    value = context.get(key)
    if value is None:
        value = context.get("event", {}).get(key)
    if value is None:
        value = context.get("business_event", {}).get(key)
    return str(value or default)


def calculate_cost_efficiency_score(
    estimated_cost_usd: float,
    expected_value_usd: float,
) -> float:
    if estimated_cost_usd == 0:
        return 0.0
    return round(expected_value_usd / estimated_cost_usd, 2)


def validate_roi(cost_efficiency_score: float) -> str:
    return "positive" if cost_efficiency_score > 1 else "negative"


def assess_business_impact(grade: str, target_users: int) -> str:
    if grade == "S" and target_users >= 300000:
        return "high_value_tier1_event"
    if grade == "S" or target_users >= 100000:
        return "high_value_event"
    if grade == "A":
        return "medium_value_event"
    return "standard_event"


def recommend_final_approval(
    estimated_cost_usd: float,
    approval_threshold: float,
    ready_pods: float,
    required_pods: float,
) -> str:
    required_pods = max(required_pods, 1)
    pod_ready_ratio = ready_pods / required_pods

    if estimated_cost_usd > approval_threshold and pod_ready_ratio < 0.7:
        return "requires_human_approval_budget_and_infra_risk"
    if estimated_cost_usd > approval_threshold:
        return "requires_human_approval_budget_exceeded"
    if pod_ready_ratio < 0.7:
        return "requires_human_approval_infra_risk"
    return "auto_approvable"


def _optional_agent_result(context: dict[str, Any], agent_key: str) -> dict[str, Any]:
    try:
        return get_agent_result(context, agent_key)
    except KeyError:
        return {}


def _cost_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cost_to_value_percent(cost_usd: float, expected_value_usd: float) -> float:
    if expected_value_usd <= 0:
        return 100.0
    return round((cost_usd / expected_value_usd) * 100, 2)


def _economic_grade(cost_to_value_percent: float, budget_exceeded: bool) -> str:
    if budget_exceeded:
        return "needs_review"
    if cost_to_value_percent <= 2:
        return "excellent"
    if cost_to_value_percent <= 5:
        return "good"
    if cost_to_value_percent <= 10:
        return "watch"
    return "poor"


def _build_candidate_economics(
    cost: dict[str, Any],
    expected_value: float,
) -> list[dict[str, Any]]:
    economics: list[dict[str, Any]] = []
    for item in cost.get("candidate_costs", []) or []:
        gross_cost = _cost_value(
            item.get("gross_cost_usd", item.get("estimated_cost_usd"))
        )
        idle_saving = _cost_value(item.get("idle_resource_saving_usd"))
        net_cost = _cost_value(
            item.get("net_cost_after_idle_reduction"),
            round(gross_cost - idle_saving, 2),
        )
        cost_percent = _cost_to_value_percent(net_cost, expected_value)
        value_per_dollar = calculate_cost_efficiency_score(net_cost, expected_value)
        budget_exceeded = bool(
            item.get("net_budget_exceeded", item.get("budget_exceeded", False))
        )
        economics.append(
            {
                "label": item.get("label"),
                "gross_cost_usd": gross_cost,
                "idle_saving_usd": idle_saving,
                "net_cost_usd": net_cost,
                "cost_to_value_percent": cost_percent,
                "value_per_dollar": value_per_dollar,
                "budget_status": "budget_exceeded" if budget_exceeded else "within_budget",
                "economic_grade": _economic_grade(cost_percent, budget_exceeded),
                "required_app_pods": item.get("required_app_pods"),
                "scale_out_pods": item.get("scale_out_pods"),
            }
        )
    return economics


def _readiness_inputs(context: dict[str, Any]) -> tuple[float, float]:
    bottleneck = _optional_agent_result(context, "bottleneck_capacity")
    infra = _optional_agent_result(context, "infra_execution")

    ready_pods = (
        bottleneck.get("ready_pods")
        or infra.get("current_app_pods")
        or _context_number(context, "ready_app_pods", 0)
        or _context_number(context, "ready_pods", 0)
    )
    required_pods = (
        bottleneck.get("required_app_pods")
        or bottleneck.get("required_pods")
        or infra.get("target_app_pods")
        or _context_number(context, "required_app_pods", 1)
    )
    return _cost_value(ready_pods), max(_cost_value(required_pods, 1), 1)


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    signals = context.get("signals", {})
    cost = get_agent_result(context, "cost")
    expected_value = float(signals.get("expected_value_usd", 4200))

    cost_total = _cost_value(cost.get("total", cost.get("estimated_cost_usd")))
    gross_cost = _cost_value(
        cost.get("gross_estimated_cost_usd", cost.get("estimated_cost_usd", cost_total))
    )
    idle_saving = _cost_value(cost.get("idle_resource_saving_usd"))
    net_cost = _cost_value(cost.get("net_cost_after_idle_reduction"), gross_cost - idle_saving)
    estimated_cost_usd = net_cost
    ratio = round(_cost_to_value_percent(net_cost, expected_value), 1)

    grade = _context_text(context, "grade", "A")
    target_users = int(_context_number(context, "target_users", 0))
    approval_threshold = _context_number(context, "event_incremental_budget_usd", 95)
    ready_pods, required_pods = _readiness_inputs(context)

    cost_efficiency_score = calculate_cost_efficiency_score(
        estimated_cost_usd,
        expected_value,
    )
    roi_validation = validate_roi(cost_efficiency_score)
    business_impact = assess_business_impact(grade, target_users)
    final_approval = recommend_final_approval(
        net_cost,
        approval_threshold,
        ready_pods,
        required_pods,
    )
    candidate_economics = _build_candidate_economics(cost, expected_value)
    selected_candidate = candidate_economics[0] if candidate_economics else None
    economic_assessment = (
        "positive"
        if roi_validation == "positive"
        and net_cost <= approval_threshold
        and ratio <= 5
        else "needs_review"
    )
    result = {
        "expected_value_usd": expected_value,
        "expected_business_value_usd": expected_value,
        "cost_ratio": f"{ratio}%",
        "override": ratio > 5,
        "estimated_cost_usd": estimated_cost_usd,
        "gross_cost_usd": gross_cost,
        "idle_saving_usd": idle_saving,
        "net_cost_usd": net_cost,
        "cost_to_value_percent": ratio,
        "value_per_dollar": cost_efficiency_score,
        "cost_efficiency_score": cost_efficiency_score,
        "roi_validation": roi_validation,
        "business_impact_assessment": business_impact,
        "final_approval_recommendation": final_approval,
        "approval_recommendation": final_approval,
        "economic_assessment": economic_assessment,
        "selected_candidate_label": selected_candidate.get("label") if selected_candidate else None,
        "candidate_economics": candidate_economics,
        "readiness_context": {
            "ready_pods": ready_pods,
            "required_pods": required_pods,
            "pod_ready_ratio": round(ready_pods / max(required_pods, 1), 2),
        },
        "economic_summary": (
            f"순비용 ${net_cost}는 예상 비즈니스 가치 ${expected_value}의 {ratio}%입니다."
        ),
        "evidence": [
            f"Cost Agent의 총비용 ${gross_cost} 값을 사용했습니다.",
            f"유휴 자원 절감 가능액은 ${idle_saving}입니다.",
            f"절감 반영 후 순비용은 ${net_cost}입니다.",
            f"예상 비즈니스 가치는 ${expected_value}입니다.",
            f"비용 비율 계산식은 {net_cost} / {expected_value} * 100 = {ratio}%입니다.",
            f"비용 1달러당 비즈니스 가치는 {cost_efficiency_score}입니다.",
            f"투자 대비 효과 판단은 {roi_validation}입니다.",
            f"비즈니스 영향 평가는 {business_impact}입니다.",
            f"최종 승인 추천은 {final_approval}입니다.",
        ],
    }
    return result, f"Net cost is {ratio}% of the expected business value."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
