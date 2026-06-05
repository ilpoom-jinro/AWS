from typing import Any

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.agent import ObserverAgent
from app.config import load_settings
from app.schemas import ObserveRequest
from app.tools.kubernetes import KubernetesClient
from app.tools.prometheus import PrometheusClient


settings = load_settings()
temporal_worker_task: asyncio.Task[None] | None = None


@activity.defn(name="observe_namespace_activity")
async def observe_namespace_activity(namespace: str) -> dict[str, Any]:
    observer = ObserverAgent(
        prometheus=PrometheusClient.from_url(settings.prometheus_url),
        kubernetes=KubernetesClient.from_cluster(),
    )
    return await observer.collect_namespace_signals(namespace)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global temporal_worker_task
    temporal_client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    worker = Worker(
        temporal_client,
        task_queue=settings.temporal_observer_task_queue,
        activities=[observe_namespace_activity],
    )
    temporal_worker_task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        temporal_worker_task.cancel()
        await asyncio.gather(temporal_worker_task, return_exceptions=True)


app = FastAPI(title="MAS Observer Agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "agent_role": settings.agent_role,
        "temporal_host": settings.temporal_host,
        "temporal_namespace": settings.temporal_namespace,
    }


@app.get("/prometheus-test")
async def prometheus_test() -> dict[str, Any]:
    result = await PrometheusClient.from_url(settings.prometheus_url).query("up")
    return {"query": "up", "result": result}


@app.get("/kubernetes-test")
def kubernetes_test(namespace: str = "mas") -> dict[str, Any]:
    snapshot = KubernetesClient.from_cluster().namespace_snapshot(namespace)
    return {"namespace": namespace, "kubernetes": snapshot}


@app.post("/observe")
async def observe(request: ObserveRequest) -> dict[str, Any]:
    signals = await observe_namespace_activity(request.namespace)
    return {
        "namespace": request.namespace,
        "signals": signals,
    }
