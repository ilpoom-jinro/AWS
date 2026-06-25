from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.agent_runtime import (
        AGENT_DATA_REQUESTS,
        AGENT_SEQUENCE,
        AGENT_TASK_QUEUES,
        broker_cache_key,
        broker_failure,
        broker_guard_failure,
        extract_required_fields,
        get_broker_cached_result,
        agents_before,
    )
    from contracts.models import AgentResponse, AgentStatus, DataRequest


AGENT_NAMES = dict(AGENT_SEQUENCE)
AGENT_ORDER = {agent_key: index for index, (agent_key, _) in enumerate(AGENT_SEQUENCE)}


@workflow.defn
class FinOpsEventWorkflow:
    @workflow.run
    async def run(
        self,
        event_id: str,
        workflow_id: str,
        initial_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = await workflow.execute_activity(
            "load_event_context",
            args=[event_id],
            start_to_close_timeout=timedelta(seconds=20),
        )

        initial_context = initial_context or {}
        context["agent_results"] = dict(initial_context.get("agent_results", {}))
        context["replan_constraints"] = dict(initial_context.get("replan_constraints", {}))
        context["replan_forbidden"] = list(initial_context.get("replan_forbidden", []))
        context["replan_from"] = initial_context.get("replan_from")
        context["replan_intent"] = initial_context.get("replan_intent")
        context["data_requests"] = []
        context["broker_cache"] = {}
        context["broker_call_log"] = []
        context["broker_total_calls"] = 0
        context["broker_agent_calls"] = {}
        context["broker_results"] = {}
        completed_agents: set[str] = set(context["agent_results"].keys())
        requested_edges: set[str] = set()
        phase = 1

        async def record_request(request: dict[str, Any]) -> None:
            nonlocal phase
            request_key = (
                f"{request['requester_agent']}:{request['source_agent']}:"
                f"{request['field']}:{request['status']}"
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

        async def run_agent_activity(
            agent_key: str,
            agent_context: dict[str, Any],
        ) -> AgentResponse:
            raw_output = await workflow.execute_activity(
                "run_finops_agent",
                args=[
                    workflow_id,
                    agent_key,
                    AGENT_NAMES[agent_key],
                    agent_context,
                ],
                task_queue=AGENT_TASK_QUEUES[agent_key],
                start_to_close_timeout=timedelta(seconds=30),
            )
            return AgentResponse.model_validate(raw_output)

        async def resolve_data_request(
            request: DataRequest,
            broker_context: dict[str, Any],
            broker_workflow_id: str,
            call_stack: list[str],
        ) -> dict[str, Any]:
            target_agent = request.target_agent
            if target_agent not in AGENT_NAMES:
                return broker_failure(
                    "unknown_agent",
                    f"Unknown FinOps agent: {target_agent}",
                )

            guard_failure = broker_guard_failure(
                broker_context,
                target_agent,
                call_stack,
            )
            if guard_failure:
                broker_context["broker_call_log"].append(
                    {
                        "target_agent": target_agent,
                        "operation": request.operation,
                        "call_stack": list(call_stack),
                        **guard_failure,
                    }
                )
                return guard_failure

            cache_key = broker_cache_key(request)
            cached = get_broker_cached_result(broker_context, request)
            if cached is not None:
                broker_context["broker_call_log"].append(
                    {
                        "target_agent": target_agent,
                        "operation": request.operation,
                        "cache_key": cache_key,
                        "cache_hit": True,
                        "_broker_status": cached.get("_broker_status"),
                    }
                )
                return cached

            broker_context["broker_total_calls"] += 1
            broker_context["broker_agent_calls"][target_agent] = (
                broker_context["broker_agent_calls"].get(target_agent, 0) + 1
            )
            call_entry = {
                "target_agent": target_agent,
                "operation": request.operation,
                "parameters": request.parameters,
                "required_fields": request.required_fields,
                "call_stack": list(call_stack),
                "cache_key": cache_key,
                "cache_hit": False,
                "call_number": broker_context["broker_total_calls"],
            }
            broker_context["broker_call_log"].append(call_entry)

            await workflow.execute_activity(
                "record_data_request",
                args=[
                    broker_workflow_id,
                    broker_context["broker_total_calls"],
                    request.model_dump(mode="json"),
                ],
                start_to_close_timeout=timedelta(seconds=10),
            )

            target_context = {
                **broker_context,
                "parameters": dict(request.parameters),
                "broker_results": dict(broker_context["broker_results"]),
            }
            response = await run_agent_activity(target_agent, target_context)

            if response.status == AgentStatus.NEEDS_DATA:
                nested_stack = [*call_stack, target_agent]
                for nested_request in response.data_requests:
                    nested_result = await resolve_data_request(
                        nested_request,
                        broker_context,
                        broker_workflow_id,
                        nested_stack,
                    )
                    broker_context["broker_results"][
                        nested_request.target_agent
                    ] = nested_result

                target_context = {
                    **broker_context,
                    "parameters": dict(request.parameters),
                    "broker_results": dict(broker_context["broker_results"]),
                }
                response = await run_agent_activity(target_agent, target_context)
                if response.status == AgentStatus.NEEDS_DATA:
                    response = response.model_copy(
                        update={
                            "status": AgentStatus.BLOCKED,
                            "warnings": [
                                *response.warnings,
                                "Agent still requested data after broker resolution",
                            ],
                        }
                    )

            if response.status != AgentStatus.COMPLETED:
                result = broker_failure(
                    f"target_agent_{response.status.value}",
                    response.message,
                )
                call_entry.update(result)
                return result

            result = extract_required_fields(response, request.required_fields)
            call_entry.update(
                {
                    "_broker_status": result["_broker_status"],
                    "response_agent": response.agent_key,
                }
            )
            if result["_broker_status"] == "completed":
                broker_context["broker_cache"][cache_key] = result
            return result

        async def execute_agent(
            agent_key: str,
            agent_name: str,
            next_agent_name: str,
        ) -> None:
            nonlocal context, phase
            await workflow.execute_activity(
                "record_agent_step_started",
                args=[workflow_id, phase, agent_key, agent_name, next_agent_name, context],
                start_to_close_timeout=timedelta(seconds=10),
            )
            response = await run_agent_activity(agent_key, context)

            if response.status == AgentStatus.NEEDS_DATA:
                for request in response.data_requests:
                    resolved = await resolve_data_request(
                        request,
                        context,
                        workflow_id,
                        [agent_key],
                    )
                    context["broker_results"][request.target_agent] = resolved

                response = await run_agent_activity(agent_key, context)
                if response.status == AgentStatus.NEEDS_DATA:
                    response = response.model_copy(
                        update={
                            "status": AgentStatus.BLOCKED,
                            "warnings": [
                                *response.warnings,
                                "Agent still requested data after broker resolution",
                            ],
                        }
                    )

            validated_output = response.model_dump(mode="json")
            context = await workflow.execute_activity(
                "record_agent_step_completed",
                args=[
                    workflow_id,
                    phase,
                    agent_key,
                    agent_name,
                    next_agent_name,
                    context,
                    validated_output,
                ],
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
                    and request["field"]
                    in context["agent_results"][source_key]["result"]
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

        skipped_agents = set()
        if context.get("replan_from"):
            skipped_agents = set(agents_before(context["replan_from"]))
        pending_agents = [
            agent_key
            for agent_key, _ in AGENT_SEQUENCE
            if agent_key not in skipped_agents
        ]
        while pending_agents:
            ready_agents = []
            for agent_key in pending_agents:
                agent_name = AGENT_NAMES[agent_key]
                missing_sources = await publish_agent_requests(agent_key, agent_name)
                if not missing_sources:
                    ready_agents.append(agent_key)

            if not ready_agents:
                raise RuntimeError(
                    f"data request graph could not be resolved: {pending_agents}"
                )

            ready_agents.sort(key=lambda key: AGENT_ORDER[key])
            agent_key = ready_agents[0]
            agent_name = AGENT_NAMES[agent_key]
            pending_agents = [key for key in pending_agents if key != agent_key]
            next_agent_name = (
                "Temporal Data Broker" if pending_agents else "FinOps Orchestrator"
            )
            await execute_agent(agent_key, agent_name, next_agent_name)

        return await workflow.execute_activity(
            "finalize_finops_plan",
            args=[workflow_id, context],
            start_to_close_timeout=timedelta(seconds=20),
        )
