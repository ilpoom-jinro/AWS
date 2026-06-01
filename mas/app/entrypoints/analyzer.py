from typing import Any

from fastapi import FastAPI, HTTPException

from app.agents.analyzer import AnalyzerAgent
from app.config import load_settings
from app.schemas import AnalyzeSignalsRequest
from app.tools.bedrock import BedrockClient, BedrockConfigError


settings = load_settings()
app = FastAPI(title="MAS Analyzer Agent", version="0.1.0")


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


@app.post("/analyze-signals")
async def analyze_signals(request: AnalyzeSignalsRequest) -> dict[str, Any]:
    try:
        analyzer = AnalyzerAgent(BedrockClient.from_env())
        analysis = analyzer.analyze_signals(request.namespace, request.signals, request.prompt)
    except BedrockConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "namespace": request.namespace,
        "analysis": analysis,
    }
