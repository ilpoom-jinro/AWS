from typing import Any

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from temporalio.client import Client
from temporalio.worker import Worker

from app.agent import OrchestratorAgent
from app.config import load_settings
from app.schemas import AnalyzeRequest
from app.temporal_workflows import NamespaceAnalysisWorkflow


settings = load_settings()
temporal_client: Client | None = None
temporal_worker_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global temporal_client, temporal_worker_task
    temporal_client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    worker = Worker(
        temporal_client,
        task_queue=settings.temporal_orchestrator_task_queue,
        workflows=[NamespaceAnalysisWorkflow],
    )
    temporal_worker_task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        temporal_worker_task.cancel()
        await asyncio.gather(temporal_worker_task, return_exceptions=True)


app = FastAPI(title="MAS Orchestrator Agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "agent_role": settings.agent_role,
        "temporal_host": settings.temporal_host,
        "temporal_namespace": settings.temporal_namespace,
    }


@app.post("/analyze")
async def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    if temporal_client is None:
        raise HTTPException(status_code=503, detail="Temporal client is not ready")

    orchestrator = OrchestratorAgent(temporal_client, settings.temporal_orchestrator_task_queue)
    try:
        return await orchestrator.analyze_namespace(request.namespace, request.prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
