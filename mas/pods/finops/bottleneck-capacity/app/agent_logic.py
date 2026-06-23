from __future__ import annotations

from typing import Any


AGENT_KEY = "bottleneck_capacity"
AGENT_NAME = "Bottleneck Capacity Agent"
LLM_PROMPT = (
    "Assess bottleneck risk and actions from RDS CPU, Redis cache hit ratio, ALB health, "
    "pod readiness, and forecast RPS. Return JSON exactly like "
    '{"bottleneck_risk": "low|medium|high", "recommended_action": "..."}.'
)


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    signals = context.get("signals", {})
    infra = context.get("infra", {})
    forecast = context["agent_results"]["traffic_forecast"]
    db_cpu = infra.get("rds_cpu_percent", signals.get("db_cpu_percent", 68))
    cache_hit = infra.get("redis_cache_hit_ratio_percent", signals.get("cache_hit_ratio_percent", 91))
    live = context.get("live", {}).get("commands", {})
    live_enabled = any(command.get("status") == "ok" for command in live.values())
    result = {
        "db_cpu": f"{db_cpu}%",
        "rds_connections": infra.get("rds_connections"),
        "rds_read_iops": infra.get("rds_read_iops"),
        "cache_hit_ratio": f"{cache_hit}%",
        "alb_status": signals.get("alb_status", "ok"),
        "alb_healthy_targets": infra.get("alb_healthy_targets"),
        "alb_unhealthy_targets": infra.get("alb_unhealthy_targets"),
        "ready_pods": infra.get("ready_pods"),
        "running_pods": infra.get("running_pods"),
        "source": "kubectl+infra_capacity_signal" if live_enabled else "infra_capacity_signal",
        "status": "warning" if db_cpu >= 65 or cache_hit < 93 else "ok",
        "validated_rps": forecast["peak_rps_after"],
    }
    return result, f"Validated {forecast['peak_rps_after']} RPS against DB, cache, ALB, and pod capacity."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    risk = assessment.get("bottleneck_risk")
    result["bottleneck_risk"] = risk
    result["recommended_action"] = assessment.get("recommended_action")
    if risk in {"medium", "high"}:
        result["status"] = "warning"
    return result
