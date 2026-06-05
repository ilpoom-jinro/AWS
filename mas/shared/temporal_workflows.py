from datetime import timedelta
from typing import Any

from temporalio import workflow

ORCHESTRATOR_TASK_QUEUE = "mas-orchestrator"
OBSERVER_TASK_QUEUE = "mas-observer-agent"
ANALYZER_TASK_QUEUE = "mas-analyzer-agent"


@workflow.defn
class NamespaceAnalysisWorkflow:
    @workflow.run
    async def run(self, namespace: str, prompt: str | None = None) -> dict[str, Any]:
        signals = await workflow.execute_activity(
            "observe_namespace_activity",
            namespace,
            task_queue=OBSERVER_TASK_QUEUE,
            start_to_close_timeout=timedelta(minutes=2),
        )

        analysis = await workflow.execute_activity(
            "analyze_signals_activity",
            {
                "namespace": namespace,
                "signals": signals,
                "prompt": prompt,
            },
            task_queue=ANALYZER_TASK_QUEUE,
            start_to_close_timeout=timedelta(minutes=5),
        )

        return {
            "namespace": namespace,
            "observation": {
                "namespace": namespace,
                "signals": signals,
            },
            "analysis": {
                "namespace": namespace,
                "analysis": analysis,
            },
        }
