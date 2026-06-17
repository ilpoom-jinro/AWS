from __future__ import annotations

from typing import Any


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


def run_agent(agent_key: str, context: dict[str, Any]) -> dict[str, Any]:
    event = context["event"]
    policy = context["policy"]

    if agent_key == "business_control":
        result = {
            "event_id": event["event_id"],
            "grade": event["grade"],
            "target_users": event["target_users"],
            "approval_required": policy["approval_required"],
            "max_delay_minutes": policy["max_general_delay_minutes"],
        }
        message = (
            f"{event['title']} 일정은 {event['grade']}등급 이벤트입니다. "
            f"대상자는 {event['target_users']:,}명이고 일반 사용자는 최대 "
            f"{policy['max_general_delay_minutes']}분까지 지연할 수 있습니다."
        )
    elif agent_key == "demand_shaping":
        delay = policy["max_general_delay_minutes"]
        result = {
            "vip": "immediate" if policy["vip_immediate"] else "batched",
            "general_users": f"spread_over_{delay}m",
            "peak_reduction_percent": 42,
        }
        message = (
            f"VIP는 즉시 발송하고 일반 사용자는 {delay}분 동안 분산하겠습니다. "
            "이 전략이면 예상 peak를 약 42% 낮출 수 있습니다."
        )
    elif agent_key == "traffic_forecast":
        shaping = context["agent_results"]["demand_shaping"]
        before = 1420
        after = 820 if shaping["peak_reduction_percent"] >= 40 else 980
        pods = 29
        result = {
            "peak_rps_before": before,
            "peak_rps_after": after,
            "required_app_pods": pods,
            "based_on": "demand_shaping",
        }
        message = (
            f"Demand Shaping 결과를 반영하면 peak는 {before} rps에서 {after} rps로 낮아집니다. "
            f"이 수준에서는 app pod {pods}개를 준비하는 계획이 적절합니다."
        )
    elif agent_key == "bottleneck_capacity":
        forecast = context["agent_results"]["traffic_forecast"]
        result = {
            "db_cpu": "68%",
            "cache_hit_ratio": "91%",
            "alb_status": "ok",
            "status": "warning",
            "validated_rps": forecast["peak_rps_after"],
        }
        message = (
            f"{forecast['peak_rps_after']} rps 기준으로 DB CPU는 68%, cache hit ratio는 91%로 예상됩니다. "
            "전체 경로는 버틸 수 있지만 cache hit ratio를 유지해야 합니다."
        )
    elif agent_key == "infra_execution":
        forecast = context["agent_results"]["traffic_forecast"]
        result = {
            "scale_out_at": "T-20m",
            "prewarm_at": "T-15m",
            "scale_down": "observed_rps_based",
            "target_app_pods": forecast["required_app_pods"],
        }
        message = (
            f"T-20분에 app pod를 {forecast['required_app_pods']}개까지 준비하고 "
            "T-15분에 CDN/cache pre-warm을 시작하겠습니다."
        )
    elif agent_key == "cost":
        infra = context["agent_results"]["infra_execution"]
        result = {
            "eks": 31.2,
            "network": 8.1,
            "logs": 3.4,
            "push": 7.6,
            "total": 50.3,
            "pod_count": infra["target_app_pods"],
        }
        message = (
            f"{infra['target_app_pods']}개 pod 준비안을 기준으로 총 비용은 약 $50.3입니다. "
            "가장 큰 항목은 EKS/EC2 용량 비용입니다."
        )
    elif agent_key == "unit_economics":
        cost = context["agent_results"]["cost"]
        result = {
            "expected_value_usd": 4200,
            "cost_ratio": "1.2%",
            "override": False,
            "estimated_cost_usd": cost["total"],
        }
        message = (
            f"예상 비즈니스 가치는 약 $4,200이고 비용 비율은 1.2%입니다. "
            "비용 대비 실행 가치는 충분하다고 판단합니다."
        )
    elif agent_key == "policy_guardrail":
        unit = context["agent_results"]["unit_economics"]
        result = {
            "allowed": ["scale_out", "prewarm", "spread_push"],
            "approval_required": policy["approval_required"],
            "cost_ratio": unit["cost_ratio"],
        }
        message = (
            "정책상 scale-out, pre-warm, push 분산은 허용됩니다. "
            "다만 S등급 이벤트이므로 운영자 승인이 필요합니다."
        )
    elif agent_key == "observer":
        result = {
            "mode": "armed",
            "watch": ["rps", "latency", "db_cpu", "cost_burn"],
            "recommendation": "scale_down_if_actual_rps_below_600",
        }
        message = (
            "실행 중에는 RPS, latency, DB CPU, 비용 burn rate를 관측하겠습니다. "
            "실제 RPS가 600 미만이면 단계적 scale-down을 권고합니다."
        )
    elif agent_key == "fallback":
        result = {"vip_only": True, "general_hold": True, "static_report": True}
        message = (
            "문제가 생기면 VIP만 우선 발송하고 일반 사용자는 hold합니다. "
            "필요하면 static report로 대체 경로를 제공합니다."
        )
    elif agent_key == "postmortem_learning":
        result = {"profile_update": "pending_after_execution", "compare": ["forecast", "actual", "cost"]}
        message = (
            "이벤트 종료 후 예측값, 실제 트래픽, 실제 비용을 비교해서 "
            "다음 이벤트 profile을 갱신하겠습니다."
        )
    else:
        raise ValueError(f"unknown agent: {agent_key}")

    return {"result": result, "message": message}


def build_final_plan(context: dict[str, Any]) -> dict[str, Any]:
    forecast = context["agent_results"]["traffic_forecast"]
    cost = context["agent_results"]["cost"]
    policy = context["agent_results"]["policy_guardrail"]
    return {
        "event_id": context["event"]["event_id"],
        "peak_rps_before": forecast["peak_rps_before"],
        "peak_rps_after": forecast["peak_rps_after"],
        "required_app_pods": forecast["required_app_pods"],
        "estimated_cost_usd": cost["total"],
        "approval_required": policy["approval_required"],
        "execution_mode": "dry_run",
        "recommended_actions": [
            "VIP 사용자는 즉시 발송",
            f"일반 사용자는 {context['policy']['max_general_delay_minutes']}분 동안 분산 발송",
            "푸시 15분 전 CDN/cache pre-warm",
            "예상 peak에 맞춰 app pod scale-out 후 실제 RPS 기반 scale-down",
        ],
    }
