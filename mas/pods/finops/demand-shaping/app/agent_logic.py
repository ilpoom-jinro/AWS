from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "demand_shaping"
AGENT_NAME = "Demand Shaping Agent"
LLM_PROMPT = (
    "Assess the send window and peak reduction for the VIP and general audiences, then "
    "recommend a better distribution strategy when appropriate. Return JSON exactly like "
    '{"recommended_window_minutes": 10, "strategy": "...", "reasoning": "..."}.'
)


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    policy = context["policy"]
    business = context.get("business", {})
    control = get_agent_result(context, "business_control")
    candidates = [
        {
            "label": "안정성 우선",
            "push_window_minutes": 10,
            "peak_reduction_percent": 42,
        },
        {
            "label": "균형",
            "push_window_minutes": 15,
            "peak_reduction_percent": 60,
        },
        {
            "label": "비용 우선",
            "push_window_minutes": 20,
            "peak_reduction_percent": 60,
        },
    ]
    delay = candidates[0]["push_window_minutes"]
    reduction = candidates[0]["peak_reduction_percent"]
    result = {
        "vip": "immediate" if policy["vip_immediate"] else "batched",
        "general_users": f"spread_over_{delay}m",
        "vip_send_mode": "immediate" if policy["vip_immediate"] else "batched",
        "general_send_mode": "spread",
        "send_window_minutes": delay,
        "peak_reduction_percent": reduction,
        "vip_audience_count": control.get(
            "vip_audience_count", business.get("vip_audience_count")
        ),
        "general_audience_count": control.get(
            "general_audience_count", business.get("general_audience_count")
        ),
        "crm_segment": business.get("crm_segment"),
        "candidates": candidates,
        "evidence": [
            f"Business Control Agent의 target_users={control.get('target_users')} 값을 사용했습니다.",
            f"VIP 발송 방식은 {'immediate' if policy['vip_immediate'] else 'batched'}입니다.",
            f"일반 사용자는 {delay}분 동안 분산 발송합니다.",
            f"선택된 후보는 '{candidates[0]['label']}'입니다.",
            f"예상 peak 감소율은 {reduction}%입니다.",
        ],
    }
    return result, f"Spread general delivery over {delay} minutes; estimated peak reduction is {reduction}%."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    value = assessment.get("recommended_window_minutes")
    recommended = value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
    if recommended:
        result["send_window_minutes"] = recommended
        result["general_users"] = f"spread_over_{recommended}m"
        result["peak_reduction_percent"] = min(60, max(10, int(recommended * 4.2)))
    result["strategy"] = assessment.get("strategy")
    result["strategy_reasoning"] = assessment.get("reasoning")
    return result
