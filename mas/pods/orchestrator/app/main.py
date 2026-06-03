from typing import Any

import httpx
from fastapi import FastAPI, HTTPException

from app.agent import OrchestratorAgent
from app.config import load_settings
from app.schemas import AnalyzeRequest


settings = load_settings()
app = FastAPI(title="MAS Orchestrator Agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "agent_role": settings.agent_role,
    }


@app.post("/analyze")
async def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    orchestrator = OrchestratorAgent(
        observer_url=settings.observer_url,
        analyzer_url=settings.analyzer_url,
    )
    try:
        return await orchestrator.analyze_namespace(request.namespace, request.prompt)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
