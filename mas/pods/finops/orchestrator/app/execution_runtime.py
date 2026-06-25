from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from contracts.models import (
    ExecutionMode,
    ExecutionStep,
    ExecutionStepStatus,
    ExecutionStepType,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_execution_steps(
    final_plan: dict,
    mode: ExecutionMode = ExecutionMode.DRY_RUN,
) -> list[ExecutionStep]:
    mode = ExecutionMode(mode)
    target_pods = int(final_plan["required_app_pods"])
    capacity = final_plan.get("report", {}).get("capacity", {})
    current_pods = capacity.get("current_app_pods", 0)
    window_minutes = final_plan.get("push_window_minutes", 10)

    specs = [
        (
            ExecutionStepType.SCALE_OUT,
            "T-20m",
            {
                "target_pods": target_pods,
                "current_pods": current_pods,
                "deployment": "app",
                "mode": mode.value,
            },
        ),
        (
            ExecutionStepType.CACHE_PREWARM,
            "T-15m",
            {"targets": ["redis", "cdn"], "mode": mode.value},
        ),
        (
            ExecutionStepType.PUSH_SCHEDULE,
            "T-10m",
            {
                "window_minutes": window_minutes,
                "vip_immediate": True,
                "mode": mode.value,
            },
        ),
        (
            ExecutionStepType.VERIFY_READY,
            "T-10m",
            {"expected_pods": target_pods, "alb_check": True, "mode": mode.value},
        ),
        (
            ExecutionStepType.GO_NO_GO,
            "T-5m",
            {"min_ready_pods": target_pods, "max_p95_ms": 200, "mode": mode.value},
        ),
        (
            ExecutionStepType.SCALE_DOWN_WATCH,
            "post_event",
            {"threshold_rps": 600, "cooldown_minutes": 10, "mode": mode.value},
        ),
    ]
    return [
        ExecutionStep(
            step_id=f"{step_type.value}-{index + 1}",
            step_type=step_type,
            scheduled_at=scheduled_at,
            parameters=parameters,
        )
        for index, (step_type, scheduled_at, parameters) in enumerate(specs)
    ]


def simulate_step(
    step: ExecutionStep,
    context: dict | None = None,
) -> ExecutionStep:
    context = context or {}
    now = utcnow()
    params = step.parameters
    if step.step_type == ExecutionStepType.SCALE_OUT:
        target_pods = params["target_pods"]
        result = {
            "action": f"kubectl scale deployment app --replicas={target_pods}",
            "simulated": True,
            "before_pods": params.get("current_pods", 0),
            "after_pods": target_pods,
            "duration_seconds": 45,
        }
    elif step.step_type == ExecutionStepType.CACHE_PREWARM:
        result = {
            "action": "redis warm + cdn prewarm",
            "simulated": True,
            "keys_warmed": 1240,
            "cdn_distributions": ["SIMULATED_DIST"],
            "duration_seconds": 30,
        }
    elif step.step_type == ExecutionStepType.PUSH_SCHEDULE:
        window_minutes = params.get("window_minutes", 10)
        result = {
            "action": "push schedule registered",
            "simulated": True,
            "vip_send_at": "T+0m",
            "general_send_window": f"{window_minutes}m",
        }
    elif step.step_type == ExecutionStepType.VERIFY_READY:
        expected_pods = params["expected_pods"]
        result = {
            "ready_pods": expected_pods,
            "alb_healthy_targets": expected_pods,
            "alb_check": "passed",
            "simulated": True,
        }
    elif step.step_type == ExecutionStepType.GO_NO_GO:
        min_ready_pods = params["min_ready_pods"]
        result = {
            "decision": "GO",
            "ready_pods": min_ready_pods,
            "p95_baseline_ms": 185,
            "simulated": True,
        }
    elif step.step_type == ExecutionStepType.SCALE_DOWN_WATCH:
        result = {
            "watching": True,
            "threshold_rps": params.get("threshold_rps", 600),
            "simulated": True,
        }
    else:
        return step.model_copy(
            update={
                "status": ExecutionStepStatus.FAILED,
                "started_at": now,
                "completed_at": now,
                "error": f"unsupported step type: {step.step_type}",
            }
        )

    return step.model_copy(
        update={
            "status": ExecutionStepStatus.SUCCESS,
            "result": result,
            "started_at": now,
            "completed_at": now,
        }
    )


def validate_execution_preconditions(
    final_plan: dict,
) -> dict:
    issues: list[str] = []
    if not final_plan.get("required_app_pods"):
        issues.append("required_app_pods missing")
    if final_plan.get("quality_gate_result", {}).get("passed") is not True:
        issues.append("quality_gate not passed")
    if not final_plan.get("recommended_candidate"):
        issues.append("recommended_candidate missing")
    return {"valid": len(issues) == 0, "issues": issues}
