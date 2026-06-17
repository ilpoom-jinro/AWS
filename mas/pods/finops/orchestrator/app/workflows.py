from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.agent_runtime import AGENT_SEQUENCE


@workflow.defn
class FinOpsEventWorkflow:
    @workflow.run
    async def run(self, event_id: str, workflow_id: str) -> dict[str, Any]:
        context = await workflow.execute_activity(
            "load_event_context",
            args=[event_id],
            start_to_close_timeout=timedelta(seconds=20),
        )

        context["agent_results"] = {}
        for phase, (agent_key, agent_name) in enumerate(AGENT_SEQUENCE, start=1):
            next_agent_name = (
                AGENT_SEQUENCE[phase][1]
                if phase < len(AGENT_SEQUENCE)
                else "FinOps Orchestrator"
            )
            context = await workflow.execute_activity(
                "run_agent_step",
                args=[workflow_id, phase, agent_key, agent_name, next_agent_name, context],
                start_to_close_timeout=timedelta(seconds=20),
            )

        return await workflow.execute_activity(
            "finalize_finops_plan",
            args=[workflow_id, context],
            start_to_close_timeout=timedelta(seconds=20),
        )
