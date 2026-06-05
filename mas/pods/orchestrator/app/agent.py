from uuid import uuid4
from typing import Any

from temporalio.client import Client

from app.temporal_workflows import NamespaceAnalysisWorkflow


class OrchestratorAgent:
    def __init__(self, temporal_client: Client, task_queue: str) -> None:
        self.temporal_client = temporal_client
        self.task_queue = task_queue

    async def analyze_namespace(self, namespace: str, prompt: str | None = None) -> dict[str, Any]:
        workflow_id = f"mas-analyze-{namespace}-{uuid4()}"
        handle = await self.temporal_client.start_workflow(
            NamespaceAnalysisWorkflow.run,
            args=[namespace, prompt],
            id=workflow_id,
            task_queue=self.task_queue,
        )
        result = await handle.result()
        return {"workflow_id": workflow_id, "result": result}
