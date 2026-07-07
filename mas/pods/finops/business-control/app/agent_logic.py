from __future__ import annotations

from typing import Any


AGENT_KEY = "business_control"
AGENT_NAME = "Business Control Agent"
LLM_PROMPT = (
    "Review whether the allowed delay and approval requirement are appropriate for the "
    "event grade, audience size, and VIP ratio. Return JSON exactly like "
    '{"assessment": "...", "risk_level": "low|medium|high"}.'
)


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    event = context["event"]
    policy = context["policy"]
    business = context.get("business", {})
    result = {
        "event_id": event["event_id"],
        "grade": event["grade"],
        "target_users": event["target_users"],
        "vip_audience_count": business.get("vip_audience_count"),
        "general_audience_count": business.get("general_audience_count"),
        "push_channel": business.get("push_channel"),
        "campaign_importance": business.get("campaign_importance"),
        "approval_required": policy["approval_required"],
        "max_delay_minutes": policy["max_general_delay_minutes"],
        "source": business.get("calendar_source", "business_calendar"),

        "evidence": [
            f"이벤트 {event['event_id']}는 grade {event['grade']}로 분류되었습니다.",
            f"대상자는 {event['target_users']:,}명입니다.",
            f"VIP 대상자는 {business.get('vip_audience_count')}명입니다.",
            f"일반 대상자는 {business.get('general_audience_count')}명입니다.",
            f"정책상 approval_required={policy['approval_required']}입니다.",
            f"일반 사용자 최대 지연 허용 시간은 {policy['max_general_delay_minutes']}분입니다.",
            f"데이터 source는 {business.get('calendar_source', 'business_calendar')}입니다.",
        ],
    }
    history = context.get("event_history", [])
    if history:
        avg_peak_rps = sum(item["actual_peak_rps"] for item in history) / len(history)
        avg_shaped_rps = sum(
            item.get("actual_shaped_rps", item["actual_peak_rps"]) for item in history
        ) / len(history)
        avg_pods = sum(item["actual_pods_used"] for item in history) / len(history)
        avg_cost = sum(float(item["actual_cost_usd"]) for item in history) / len(history)
        avg_p95 = sum(item["actual_p95_ms"] for item in history) / len(history)
        result.update(
            {
                "baseline_peak_rps": round(avg_peak_rps),
                "historical_avg_peak_rps": round(avg_peak_rps),
                "historical_avg_shaped_rps": round(avg_shaped_rps),
                "historical_avg_pods": round(avg_pods, 1),
                "historical_avg_cost_usd": round(avg_cost, 2),
                "historical_avg_p95_ms": round(avg_p95),
                "historical_event_count": len(history),
                "historical_events": [
                    {
                        "date": str(item["event_date"]),
                        "peak_rps": item["actual_peak_rps"],
                        "shaped_rps": item.get("actual_shaped_rps"),
                        "pods": item["actual_pods_used"],
                        "cost_usd": float(item["actual_cost_usd"]),
                        "p95_ms": item["actual_p95_ms"],
                    }
                    for item in history
                ],
            }
        )
    else:
        result["baseline_peak_rps"] = int(context.get("baseline_peak_rps", 1400) or 1400)
        result["historical_event_count"] = 0
        result["historical_events"] = []
        result["warnings"] = ["No historical event data available; using default baseline."]
    message = (
        f"Classified {event['title']} as grade {event['grade']} for "
        f"{event['target_users']:,} users with a maximum general delay of "
        f"{policy['max_general_delay_minutes']} minutes."
    )
    return result, message


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    result["assessment"] = assessment.get("assessment")
    result["risk_level"] = assessment.get("risk_level")
    return result
