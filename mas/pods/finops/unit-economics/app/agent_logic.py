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


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    signals = context.get("signals", {})
    cost = get_agent_result(context, "cost")
    expected_value = float(signals.get("expected_value_usd", 4200))
    ratio = round((cost["total"] / expected_value) * 100, 1) if expected_value else 100.0
    estimated_cost_usd = float(cost["total"])
    grade = _context_text(context, "grade", "A")
    target_users = int(_context_number(context, "target_users", 0))
    approval_threshold = _context_number(context, "event_incremental_budget_usd", 95)
    ready_pods = _context_number(context, "ready_app_pods", 0)
    if not ready_pods:
        ready_pods = _context_number(context, "ready_pods", 0)
    required_pods = max(_context_number(context, "required_app_pods", 1), 1)
    if required_pods == 1:
        required_pods = max(_context_number(context, "target_app_pods", 1), 1)

    cost_efficiency_score = calculate_cost_efficiency_score(
        estimated_cost_usd,
        expected_value,
    )
    roi_validation = validate_roi(cost_efficiency_score)
    business_impact = assess_business_impact(grade, target_users)
    final_approval = recommend_final_approval(
        estimated_cost_usd,
        approval_threshold,
        ready_pods,
        required_pods,
    )
    result = {
        "expected_value_usd": expected_value,
        "cost_ratio": f"{ratio}%",
        "override": ratio > 5,
        "estimated_cost_usd": estimated_cost_usd,
        "cost_efficiency_score": cost_efficiency_score,
         "roi_validation": roi_validation,
        "business_impact_assessment": business_impact,
        "final_approval_recommendation": final_approval,
        "evidence": [
            f"Cost Agent의 total=${cost['total']} 값을 사용했습니다.",
            f"예상 비즈니스 가치는 ${expected_value}입니다.",
            f"비용 비율 계산식은 {cost['total']} / {expected_value} * 100 = {ratio}%입니다.",
            f"cost_efficiency_score={cost_efficiency_score}입니다.",
            f"ROI 판단은 {roi_validation}입니다.",
            f"비즈니스 영향 평가는 {business_impact}입니다.",
            f"최종 승인 추천은 {final_approval}입니다.",
        ],
    }
    return result, f"Incremental cost is {ratio}% of the expected business value."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
