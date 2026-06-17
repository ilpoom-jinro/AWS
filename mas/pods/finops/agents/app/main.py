import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


AGENT_KEY = os.getenv("AGENT_KEY", "business_control")
AGENT_NAME = os.getenv("AGENT_NAME", "Business Control Agent")

app = FastAPI(title=AGENT_NAME, version="0.1.0")


class AgentRequest(BaseModel):
    workflow_id: str
    context: dict[str, Any]


def event_policy(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return context["event"], context["policy"]


def run_agent(agent_key: str, context: dict[str, Any]) -> dict[str, Any]:
    event, policy = event_policy(context)
    previous = context.get("agent_results", {})

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
            f"Business Control 결과를 반영해 VIP는 즉시 발송하고 일반 사용자는 {delay}분 동안 분산하겠습니다. "
            "예상 피크를 약 42% 낮출 수 있습니다."
        )
    elif agent_key == "traffic_forecast":
        shaping = previous["demand_shaping"]
        before = 1420
        after = 820 if shaping["peak_reduction_percent"] >= 40 else 980
        result = {
            "peak_rps_before": before,
            "peak_rps_after": after,
            "required_app_pods": 29,
            "based_on": "demand_shaping",
        }
        message = (
            f"Demand Shaping의 {shaping['general_users']} 전략을 반영하면 피크는 "
            f"{before} rps에서 {after} rps로 낮아집니다. app pod는 29개가 필요합니다."
        )
    elif agent_key == "bottleneck_capacity":
        forecast = previous["traffic_forecast"]
        result = {
            "db_cpu": "68%",
            "cache_hit_ratio": "91%",
            "alb_status": "ok",
            "status": "warning",
            "validated_rps": forecast["peak_rps_after"],
        }
        message = (
            f"{forecast['peak_rps_after']} rps 기준으로 DB CPU는 68%, 캐시 hit ratio는 91%입니다. "
            "병목은 경고 수준이지만 실행 가능합니다."
        )
    elif agent_key == "cost":
        forecast = previous["traffic_forecast"]
        result = {
            "eks": 31.2,
            "network": 8.1,
            "logs": 3.4,
            "push": 7.6,
            "total": 50.3,
            "pod_count": forecast["required_app_pods"],
        }
        message = (
            f"{forecast['required_app_pods']}개 pod 기준 총 비용은 약 $50.3입니다. "
            "가장 큰 비용은 EKS/EC2 용량입니다."
        )
    elif agent_key == "policy_guardrail":
        result = {
            "allowed": ["scale_out", "prewarm", "spread_push"],
            "approval_required": policy["approval_required"],
        }
        message = (
            "정책상 scale-out, pre-warm, push 분산은 허용됩니다. "
            "S등급 이벤트이므로 운영자 승인이 필요합니다."
        )
    else:
        result = {"status": "skipped", "agent_key": agent_key}
        message = f"{AGENT_NAME}은 현재 외부 pod가 아니라 orchestrator 내부 fallback으로 처리됩니다."

    return {"agent": AGENT_NAME, "agent_key": agent_key, "result": result, "message": message}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME, "agent_key": AGENT_KEY}


@app.post("/run")
def run(request: AgentRequest) -> dict[str, Any]:
    return run_agent(AGENT_KEY, request.context)
