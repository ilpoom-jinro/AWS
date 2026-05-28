from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.agents.analyzer import AnalyzerAgent
from app.agents.observer import ObserverAgent
from app.agents.runtime import RuntimeAgent
from app.config import load_settings
from app.tools.bedrock import BedrockClient, BedrockConfigError
from app.tools.kubernetes import KubernetesClient
from app.tools.prometheus import PrometheusClient


class AnalyzeRequest(BaseModel):
    namespace: str = "argocd"
    prompt: str | None = None


settings = load_settings()
app = FastAPI(title="MAS Runtime", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "agent_role": settings.agent_role,
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


@app.get("/prometheus-test")
async def prometheus_test() -> dict[str, Any]:
    result = await PrometheusClient.from_url(settings.prometheus_url).query("up")
    return {"query": "up", "result": result}


@app.get("/kubernetes-test")
def kubernetes_test(namespace: str = "mas") -> dict[str, Any]:
    pods = KubernetesClient.from_cluster().list_pods(namespace)
    return {"namespace": namespace, "pods": pods}


@app.post("/analyze")
async def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    try:
        runtime = RuntimeAgent(
            observer=ObserverAgent(PrometheusClient.from_url(settings.prometheus_url)),
            analyzer=AnalyzerAgent(BedrockClient.from_env()),
        )
        return await runtime.analyze_namespace(request.namespace, request.prompt)
    except BedrockConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
