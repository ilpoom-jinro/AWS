from typing import Any

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.agent import AnalyzerAgent
from app.config import load_settings
from app.schemas import AnalyzeSignalsRequest
from app.tools.bedrock import BedrockClient, BedrockConfigError


settings = load_settings()
temporal_worker_task: asyncio.Task[None] | None = None


@activity.defn(name="analyze_signals_activity")
async def analyze_signals_activity(payload: dict[str, Any]) -> dict[str, Any]:
    analyzer = AnalyzerAgent(BedrockClient.from_env())
    return analyzer.analyze_signals(payload["namespace"], payload["signals"], payload.get("prompt"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global temporal_worker_task
    temporal_client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    worker = Worker(
        temporal_client,
        task_queue=settings.temporal_analyzer_task_queue,
        activities=[analyze_signals_activity],
    )
    temporal_worker_task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        temporal_worker_task.cancel()
        await asyncio.gather(temporal_worker_task, return_exceptions=True)


app = FastAPI(title="MAS Analyzer Agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "agent_role": settings.agent_role,
        "temporal_host": settings.temporal_host,
        "temporal_namespace": settings.temporal_namespace,
    }


@app.get("/bedrock-test")
def bedrock_test() -> dict[str, Any]:
    try:
        response = BedrockClient.from_env().converse(
            "Reply with one short sentence confirming that MAS can reach Bedrock."
        )
    except BedrockConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"model_id": settings.bedrock_model_id, "response": response}


@app.post("/analyze-signals")
async def analyze_signals(request: AnalyzeSignalsRequest) -> dict[str, Any]:
    try:
        analysis = await analyze_signals_activity(
            {
                "namespace": request.namespace,
                "signals": request.signals,
                "prompt": request.prompt,
            }
        )
    except BedrockConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "namespace": request.namespace,
        "analysis": analysis,
    }
