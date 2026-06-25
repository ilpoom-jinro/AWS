from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "mas"
ORCHESTRATOR = ROOT / "mas" / "pods" / "finops" / "orchestrator"
for path in (CONTRACTS, ORCHESTRATOR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.execution_runtime import (  # noqa: E402
    build_execution_steps,
    simulate_step,
    validate_execution_preconditions,
)
from contracts.models import ExecutionMode, ExecutionPlan, ExecutionStepStatus, ExecutionStepType  # noqa: E402


def sample_final_plan() -> dict:
    return {
        "event_id": "normal-event",
        "required_app_pods": 22,
        "push_window_minutes": 15,
        "recommended_candidate": {"label": "균형"},
        "quality_gate_result": {"passed": True},
        "report": {"capacity": {"current_app_pods": 12}},
    }


class EventExecutionTests(unittest.TestCase):
    def test_build_execution_steps_has_six_ordered_dry_run_steps(self) -> None:
        steps = build_execution_steps(sample_final_plan(), ExecutionMode.DRY_RUN)

        self.assertEqual(len(steps), 6)
        self.assertEqual(
            [step.step_type for step in steps],
            [
                ExecutionStepType.SCALE_OUT,
                ExecutionStepType.CACHE_PREWARM,
                ExecutionStepType.PUSH_SCHEDULE,
                ExecutionStepType.VERIFY_READY,
                ExecutionStepType.GO_NO_GO,
                ExecutionStepType.SCALE_DOWN_WATCH,
            ],
        )
        self.assertTrue(all(step.parameters["mode"] == "dry_run" for step in steps))

    def test_build_execution_steps_contains_required_parameters(self) -> None:
        steps = build_execution_steps(sample_final_plan())
        by_type = {step.step_type: step for step in steps}

        scale_out = by_type[ExecutionStepType.SCALE_OUT]
        self.assertEqual(scale_out.step_id, "scale_out-1")
        self.assertEqual(scale_out.scheduled_at, "T-20m")
        self.assertEqual(scale_out.parameters["target_pods"], 22)
        self.assertEqual(scale_out.parameters["current_pods"], 12)
        self.assertEqual(scale_out.parameters["deployment"], "app")

        push = by_type[ExecutionStepType.PUSH_SCHEDULE]
        self.assertEqual(push.parameters["window_minutes"], 15)
        self.assertIs(push.parameters["vip_immediate"], True)

    def test_simulate_scale_out_step_returns_successful_mock_result(self) -> None:
        step = build_execution_steps(sample_final_plan())[0]
        executed = simulate_step(step)

        self.assertEqual(executed.status, ExecutionStepStatus.SUCCESS)
        self.assertIs(executed.result["simulated"], True)
        self.assertEqual(executed.result["before_pods"], 12)
        self.assertEqual(executed.result["after_pods"], 22)
        self.assertIn("kubectl scale", executed.result["action"])
        self.assertIsNotNone(executed.started_at)
        self.assertIsNotNone(executed.completed_at)

    def test_simulate_go_no_go_step_returns_go_decision(self) -> None:
        steps = build_execution_steps(sample_final_plan())
        go_step = next(step for step in steps if step.step_type == ExecutionStepType.GO_NO_GO)
        executed = simulate_step(go_step)

        self.assertEqual(executed.status, ExecutionStepStatus.SUCCESS)
        self.assertEqual(executed.result["decision"], "GO")
        self.assertEqual(executed.result["ready_pods"], 22)
        self.assertIs(executed.result["simulated"], True)

    def test_validate_execution_preconditions_blocks_invalid_plan(self) -> None:
        invalid_plan = {
            "required_app_pods": None,
            "quality_gate_result": {"passed": False},
            "recommended_candidate": None,
        }

        result = validate_execution_preconditions(invalid_plan)

        self.assertIs(result["valid"], False)
        self.assertIn("required_app_pods missing", result["issues"])
        self.assertIn("quality_gate not passed", result["issues"])
        self.assertIn("recommended_candidate missing", result["issues"])

    def test_execution_plan_model_accepts_generated_steps(self) -> None:
        steps = build_execution_steps(sample_final_plan())
        plan = ExecutionPlan(
            planning_workflow_id="finops-normal",
            execution_workflow_id="exec-finops-normal",
            event_id="normal-event",
            mode=ExecutionMode.DRY_RUN,
            steps=steps,
            overall_status="running",
            created_at="2026-06-25T00:00:00+00:00",
        )

        dumped = plan.model_dump(mode="json")

        self.assertEqual(dumped["mode"], "dry_run")
        self.assertEqual(dumped["steps"][0]["step_type"], "scale_out")
        self.assertEqual(dumped["steps"][0]["status"], "pending")
