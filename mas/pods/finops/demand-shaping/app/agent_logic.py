from __future__ import annotations

from typing import Any


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
    previous = context.get("agent_results", {})
    control = previous.get("business_control", {})
    delay = control.get("max_delay_minutes", policy["max_general_delay_minutes"])
    reduction = min(60, max(10, int(delay * 4.2)))
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
