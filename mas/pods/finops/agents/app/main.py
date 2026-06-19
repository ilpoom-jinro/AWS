import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


AGENT_KEY = os.getenv("AGENT_KEY", "business_control")
AGENT_NAME = os.getenv("AGENT_NAME", "Business Control Agent")

AGENT_DATA_REQUESTS = {
    "demand_shaping": [
        {
            "source_key": "business_control",
            "source_name": "Business Control Agent",
            "field": "max_delay_minutes",
            "label": "일반 사용자 허용 지연 시간",
            "reason": "푸시 분산 구간을 정하려면 정책상 허용 지연 시간이 필요합니다.",
        },
    ],
    "traffic_forecast": [
        {
            "source_key": "demand_shaping",
            "source_name": "Demand Shaping Agent",
            "field": "peak_reduction_percent",
            "label": "분산 발송 후 예상 peak 감소율",
            "reason": "평탄화 후 RPS를 다시 계산하기 위한 보정값입니다.",
        },
        {
            "source_key": "business_control",
            "source_name": "Business Control Agent",
            "field": "target_users",
            "label": "대상 사용자 수",
            "reason": "푸시 대상 규모를 기준으로 원래 peak를 추정합니다.",
        },
    ],
    "bottleneck_capacity": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "peak_rps_after",
            "label": "병목 검증 기준 RPS",
            "reason": "DB/cache/LB가 감당해야 할 트래픽 기준입니다.",
        },
    ],
    "cost": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "required_app_pods",
            "label": "비용 계산 기준 pod 수",
            "reason": "임시 비용 모델에서 app pod 수를 비용 산정 기준으로 사용합니다.",
        },
    ],
    "policy_guardrail": [
        {
            "source_key": "cost",
            "source_name": "Cost Agent",
            "field": "total",
            "label": "예상 총 비용",
            "reason": "정책상 승인 또는 차단 여부를 판단합니다.",
        },
    ],
}

AGENT_CONFIDENCE = {
    "business_control": 0.91,
    "demand_shaping": 0.86,
    "traffic_forecast": 0.82,
    "bottleneck_capacity": 0.78,
    "cost": 0.8,
    "policy_guardrail": 0.9,
}

app = FastAPI(title=AGENT_NAME, version="0.3.0")


class AgentRequest(BaseModel):
    workflow_id: str
    context: dict[str, Any]
    available_results: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None


def event_policy(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return context["event"], context["policy"]


def data_requests_for(agent_key: str, available_results: dict[str, Any]) -> list[dict[str, Any]]:
    requests = []
    for request in AGENT_DATA_REQUESTS.get(agent_key, []):
        source_result = available_results.get(request["source_key"], {})
        status = "available" if request["field"] in source_result else "requested"
        requests.append({**request, "status": status})
    return requests


def response(
    agent_key: str,
    result: dict[str, Any],
    message: str,
    available_results: dict[str, Any],
) -> dict[str, Any]:
    return {
        "agent": AGENT_NAME,
        "agent_key": agent_key,
        "result": result,
        "message": message,
        "data_requests": data_requests_for(agent_key, available_results),
        "confidence": AGENT_CONFIDENCE.get(agent_key, 0.75),
    }


def run_agent(agent_key: str, context: dict[str, Any], available_results: dict[str, Any]) -> dict[str, Any]:
    event, policy = event_policy(context)
    signals = context.get("signals", {})
    previous = available_results or context.get("agent_results", {})

    if agent_key == "business_control":
        result = {
            "event_id": event["event_id"],
            "grade": event["grade"],
            "target_users": event["target_users"],
            "approval_required": policy["approval_required"],
            "max_delay_minutes": policy["max_general_delay_minutes"],
        }
        message = (
            f"{event['title']} 일정을 확인했습니다. 이벤트 등급은 {event['grade']}이고, "
            f"대상자는 {event['target_users']:,}명입니다. 운영자 승인은 필요합니다."
        )
    elif agent_key == "demand_shaping":
        delay = policy["max_general_delay_minutes"]
        result = {
            "vip": "immediate" if policy["vip_immediate"] else "batched",
            "general_users": f"spread_over_{delay}m",
            "peak_reduction_percent": 42,
        }
        message = (
            f"Business Control Agent가 준 허용 지연 시간 {delay}분을 사용하겠습니다. "
            "VIP는 즉시 발송하고 일반 사용자는 분산해서 예상 peak를 42% 낮추겠습니다."
        )
    elif agent_key == "traffic_forecast":
        shaping = previous["demand_shaping"]
        before = signals.get("baseline_peak_rps", 1420)
        after = signals.get("shaped_peak_rps", 820 if shaping["peak_reduction_percent"] >= 40 else 980)
        pods = signals.get("required_app_pods", 29)
        result = {
            "peak_rps_before": before,
            "peak_rps_after": after,
            "required_app_pods": pods,
            "based_on": "demand_shaping",
        }
        message = (
            f"Demand Shaping Agent의 감소율 {shaping['peak_reduction_percent']}%를 반영했습니다. "
            f"평탄화 전 peak는 {before} rps, 평탄화 후 peak는 {after} rps이고 app pod는 {pods}개가 필요합니다."
        )
    elif agent_key == "bottleneck_capacity":
        forecast = previous["traffic_forecast"]
        db_cpu = signals.get("db_cpu_percent", 68)
        cache_hit_ratio = signals.get("cache_hit_ratio_percent", 91)
        result = {
            "db_cpu": f"{db_cpu}%",
            "cache_hit_ratio": f"{cache_hit_ratio}%",
            "alb_status": signals.get("alb_status", "ok"),
            "status": "warning" if db_cpu >= 65 or cache_hit_ratio < 93 else "ok",
            "validated_rps": forecast["peak_rps_after"],
        }
        message = (
            f"{forecast['peak_rps_after']} rps 기준으로 병목을 검증했습니다. "
            f"DB CPU는 {db_cpu}%, cache hit ratio는 {cache_hit_ratio}%라서 경고 수준이지만 실행은 가능합니다."
        )
    elif agent_key == "cost":
        forecast = previous["traffic_forecast"]
        eks = float(signals.get("eks_cost_usd", 31.2))
        network = float(signals.get("network_cost_usd", 8.1))
        logs = float(signals.get("log_cost_usd", 3.4))
        push = float(signals.get("push_cost_usd", 7.6))
        total = round(eks + network + logs + push, 2)
        result = {
            "eks": eks,
            "network": network,
            "logs": logs,
            "push": push,
            "total": total,
            "pod_count": forecast["required_app_pods"],
        }
        message = (
            f"app pod {forecast['required_app_pods']}개 기준으로 예상 이벤트 비용은 총 ${total}입니다. "
            f"EKS ${eks}, 네트워크 ${network}, 로그 ${logs}, push ${push}를 포함합니다."
        )
    elif agent_key == "policy_guardrail":
        result = {
            "allowed": ["scale_out", "prewarm", "spread_push"],
            "approval_required": policy["approval_required"],
        }
        message = (
            "정책상 scale-out, pre-warm, push 분산은 허용됩니다. "
            "S등급 이벤트이므로 실제 실행 전 운영자 승인이 필요합니다."
        )
    else:
        result = {"status": "skipped", "agent_key": agent_key}
        message = f"{AGENT_NAME}는 아직 별도 pod 로직이 없어 orchestrator 내부 fallback 결과를 사용합니다."

    return response(agent_key, result, message, previous)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME, "agent_key": AGENT_KEY}


@app.post("/run")
def run(request: AgentRequest) -> dict[str, Any]:
    return run_agent(AGENT_KEY, request.context, request.available_results)
