from __future__ import annotations

from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "demand_shaping"
AGENT_NAME = "Demand Shaping Agent"
LLM_PROMPT = (
    "Assess the send window for the VIP and general audiences, then recommend "
    "a better distribution strategy when appropriate. Return JSON exactly like "
    '{"recommended_window_minutes": 10, "strategy": "...", "reasoning": "..."}.'
)


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    policy = context["policy"]
    business = context.get("business", {})
    control = get_agent_result(context, "business_control")

    max_delay = int(control.get("max_delay_minutes") or policy["max_general_delay_minutes"])
    vip_count = int(control.get("vip_audience_count") or business.get("vip_audience_count") or 0)
    general_count = int(
        control.get("general_audience_count")
        or business.get("general_audience_count")
        or max(0, int(control.get("target_users") or 0) - vip_count)
    )
    total_users = int(control.get("target_users") or vip_count + general_count)

    windows = [max_delay, max_delay + 5, max_delay + 10]
    labels = ["안정성 우선", "균형", "비용 우선"]
    candidates = [
        _build_candidate(
            label=label,
            window_minutes=window,
            vip_count=vip_count,
            general_count=general_count,
            vip_immediate=policy["vip_immediate"],
        )
        for label, window in zip(labels, windows, strict=True)
    ]
    selected = candidates[0]
    peak_reduction_percent = _estimate_peak_reduction_percent(
        selected,
        total_users=total_users,
        general_count=general_count,
    )

    result = {
        "vip": selected["vip_send_mode"],
        "general_users": selected["general_send_mode"],
        "vip_send_mode": selected["vip_send_mode"],
        "general_send_mode": selected["general_send_mode"],
        "send_window_minutes": selected["send_window_minutes"],
        "per_minute_general": selected["per_minute_general"],
        "per_second_general": selected["per_second_general"],
        "vip_count": vip_count,
        "general_count": general_count,
        "total_users": total_users,
        "vip_audience_count": vip_count,
        "general_audience_count": general_count,
        "peak_reduction_percent": peak_reduction_percent,
        "crm_segment": business.get("crm_segment"),
        "candidates": candidates,
        "evidence": [
            f"Business Control Agent의 target_users={control.get('target_users')} 값을 사용했습니다.",
            f"VIP 발송 방식은 {selected['vip_send_mode']}입니다.",
            f"일반 사용자는 {selected['send_window_minutes']}분 동안 균등 분산합니다.",
            f"일반 사용자 분당 발송량은 {selected['per_minute_general']}명입니다.",
            f"일반 사용자 초당 발송량은 {selected['per_second_general']}명입니다.",
            f"선택된 후보는 '{selected['label']}'입니다.",
        ],
    }
    return (
        result,
        (
            f"Spread {general_count:,} general users over "
            f"{selected['send_window_minutes']} minutes "
            f"({selected['per_second_general']} users/sec)."
        ),
    )


def _build_candidate(
    *,
    label: str,
    window_minutes: int,
    vip_count: int,
    general_count: int,
    vip_immediate: bool,
) -> dict[str, Any]:
    window = max(1, int(window_minutes))
    return {
        "label": label,
        "send_window_minutes": window,
        "push_window_minutes": window,
        "vip_send_mode": "즉시 발송" if vip_immediate else "일괄 발송",
        "general_send_mode": f"{window}분 균등 분산",
        "per_minute_general": round(general_count / window, 1),
        "per_second_general": round(general_count / (window * 60), 1),
        "vip_count": vip_count,
        "general_count": general_count,
    }


def _estimate_peak_reduction_percent(
    candidate: dict[str, Any],
    *,
    total_users: int,
    general_count: int,
) -> int:
    if total_users <= 0 or general_count <= 0:
        return 0

    general_ratio = min(1.0, max(0.0, general_count / total_users))
    window = int(candidate.get("send_window_minutes") or 1)
    if window >= 15:
        distribution_effect = 0.68
    elif window >= 10:
        distribution_effect = 0.48
    else:
        distribution_effect = max(0.10, min(0.48, window * 0.048))
    return int(round(general_ratio * distribution_effect * 100))


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    value = assessment.get("recommended_window_minutes")
    recommended = value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
    if recommended:
        result["send_window_minutes"] = recommended
        result["general_users"] = f"{recommended}분 균등 분산"
    result["strategy"] = assessment.get("strategy")
    result["strategy_reasoning"] = assessment.get("reasoning")
    return result
