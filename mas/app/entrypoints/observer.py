from typing import Any

from fastapi import FastAPI

from app.agents.observer import ObserverAgent
from app.config import load_settings
from app.schemas import ObserveRequest
from app.tools.kubernetes import KubernetesClient
from app.tools.prometheus import PrometheusClient


settings = load_settings()
app = FastAPI(title="MAS Observer Agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "agent_role": settings.agent_role,
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
    observer = ObserverAgent(
        prometheus=PrometheusClient.from_url(settings.prometheus_url),
        kubernetes=KubernetesClient.from_cluster(),
    )
    signals = await observer.collect_namespace_signals(request.namespace)
    return {
        "namespace": request.namespace,
        "signals": signals,
    }
