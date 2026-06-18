from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.agent_runtime import AGENT_DATA_REQUESTS, AGENT_SEQUENCE


AGENT_NAMES = dict(AGENT_SEQUENCE)


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
        context["data_requests"] = []
        completed_agents: set[str] = set()
        phase = 1

        async def execute_agent(agent_key: str, agent_name: str, next_agent_name: str) -> None:
            nonlocal context, phase
            context = await workflow.execute_activity(
                "run_agent_step",
                args=[workflow_id, phase, agent_key, agent_name, next_agent_name, context],
                start_to_close_timeout=timedelta(seconds=20),
            )
            completed_agents.add(agent_key)
            phase += 1

        for index, (agent_key, agent_name) in enumerate(AGENT_SEQUENCE):
            for request in AGENT_DATA_REQUESTS.get(agent_key, []):
                source_key = request["source_key"]
                source_name = request["source_name"]
                context["data_requests"].append(
                    {
                        "requester_agent": agent_key,
                        "requester_name": agent_name,
                        "source_agent": source_key,
                        "source_name": source_name,
                        "field": request["field"],
                        "label": request["label"],
                        "status": (
                            "available"
                            if source_key in context["agent_results"]
                            else "pending_dynamic_activity"
                        ),
                    }
                )
                if source_key not in context["agent_results"]:
                    await execute_agent(
                        source_key,
                        AGENT_NAMES.get(source_key, source_name),
                        agent_name,
                    )

            if agent_key not in completed_agents:
                next_agent_name = (
                    AGENT_SEQUENCE[index + 1][1]
                    if index + 1 < len(AGENT_SEQUENCE)
                    else "FinOps Orchestrator"
                )
                await execute_agent(agent_key, agent_name, next_agent_name)

        return await workflow.execute_activity(
            "finalize_finops_plan",
            args=[workflow_id, context],
            start_to_close_timeout=timedelta(seconds=20),
        )
