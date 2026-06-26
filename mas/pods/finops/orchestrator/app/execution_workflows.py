from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from contracts.models import ExecutionStepStatus


@workflow.defn
class EventExecutionWorkflow:
    @workflow.run
    async def run(
        self,
        planning_workflow_id: str,
        execution_workflow_id: str,
        event_id: str,
        mode: str = "dry_run",
    ) -> dict[str, Any]:
        loaded = await workflow.execute_activity(
            "load_execution_plan",
            args=[planning_workflow_id, execution_workflow_id, event_id, mode],
            start_to_close_timeout=timedelta(seconds=20),
        )
        precondition = loaded["precondition_result"]
        if not precondition["valid"]:
            await workflow.execute_activity(
                "save_execution_plan",
                args=[
                    execution_workflow_id,
                    planning_workflow_id,
                    event_id,
                    mode,
                    loaded["steps"],
                    "failed",
                ],
                start_to_close_timeout=timedelta(seconds=10),
            )
            return await workflow.execute_activity(
                "finalize_execution",
                args=[execution_workflow_id, "failed", workflow.now().isoformat()],
                start_to_close_timeout=timedelta(seconds=10),
            )

        await workflow.execute_activity(
            "save_execution_plan",
            args=[
                execution_workflow_id,
                planning_workflow_id,
                event_id,
                mode,
                loaded["steps"],
                "running",
            ],
            start_to_close_timeout=timedelta(seconds=10),
        )

        overall_status = "completed"
        executed_steps = []
        for step in loaded["steps"]:
            executed = await workflow.execute_activity(
                "execute_step",
                args=[execution_workflow_id, step],
                start_to_close_timeout=timedelta(seconds=20),
            )
            executed_steps.append(executed)
            if executed.get("status") == ExecutionStepStatus.FAILED.value:
                overall_status = "failed"
                break

        return await workflow.execute_activity(
            "finalize_execution",
            args=[execution_workflow_id, overall_status, workflow.now().isoformat()],
            start_to_close_timeout=timedelta(seconds=10),
        )
