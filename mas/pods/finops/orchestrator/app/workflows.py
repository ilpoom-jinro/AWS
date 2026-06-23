from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.agent_runtime import AGENT_DATA_REQUESTS, AGENT_SEQUENCE, AGENT_TASK_QUEUES


AGENT_NAMES = dict(AGENT_SEQUENCE)
AGENT_ORDER = {agent_key: index for index, (agent_key, _) in enumerate(AGENT_SEQUENCE)}


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
        requested_edges: set[str] = set()
        phase = 1

        async def record_request(request: dict[str, Any]) -> None:
            nonlocal phase
            request_key = (
                f"{request['requester_agent']}:{request['source_agent']}:{request['field']}:{request['status']}"
            )
            if request_key in requested_edges:
                return
            requested_edges.add(request_key)
            context["data_requests"].append(request)
            await workflow.execute_activity(
                "record_data_request",
                args=[workflow_id, phase, request],
                start_to_close_timeout=timedelta(seconds=10),
            )
            phase += 1

        async def execute_agent(agent_key: str, agent_name: str, next_agent_name: str) -> None:
            nonlocal context, phase
            await workflow.execute_activity(
                "record_agent_step_started",
                args=[workflow_id, phase, agent_key, agent_name, next_agent_name, context],
                start_to_close_timeout=timedelta(seconds=10),
            )
            raw_output = await workflow.execute_activity(
                "run_finops_agent",
                args=[workflow_id, agent_key, agent_name, context],
                task_queue=AGENT_TASK_QUEUES[agent_key],
                start_to_close_timeout=timedelta(seconds=30),
            )
            context = await workflow.execute_activity(
                "record_agent_step_completed",
                args=[workflow_id, phase, agent_key, agent_name, next_agent_name, context, raw_output],
                start_to_close_timeout=timedelta(seconds=20),
            )
            completed_agents.add(agent_key)
            phase += 1

        async def publish_agent_requests(agent_key: str, agent_name: str) -> list[str]:
            missing_sources = []
            for request in AGENT_DATA_REQUESTS.get(agent_key, []):
                source_key = request["source_key"]
                status = (
                    "available"
                    if source_key in context["agent_results"]
                    else "pending_dynamic_activity"
                )
                await record_request(
                    {
                        "requester_agent": agent_key,
                        "requester_name": agent_name,
                        "source_agent": source_key,
                        "source_name": request["source_name"],
                        "field": request["field"],
                        "label": request["label"],
                        "reason": request.get("reason", ""),
                        "status": status,
                    }
                )
                if status != "available":
                    missing_sources.append(source_key)
            return missing_sources

        pending_agents = [agent_key for agent_key, _ in AGENT_SEQUENCE]
        while pending_agents:
            ready_agents = []
            for agent_key in pending_agents:
                agent_name = AGENT_NAMES[agent_key]
                missing_sources = await publish_agent_requests(agent_key, agent_name)
                if not missing_sources:
                    ready_agents.append(agent_key)

            if not ready_agents:
                raise RuntimeError(f"data request graph could not be resolved: {pending_agents}")

            ready_agents.sort(key=lambda key: AGENT_ORDER[key])
            agent_key = ready_agents[0]
            agent_name = AGENT_NAMES[agent_key]
            pending_agents = [key for key in pending_agents if key != agent_key]
            next_agent_name = "Temporal Data Broker" if pending_agents else "FinOps Orchestrator"
            await execute_agent(agent_key, agent_name, next_agent_name)

        return await workflow.execute_activity(
            "finalize_finops_plan",
            args=[workflow_id, context],
            start_to_close_timeout=timedelta(seconds=20),
        )
