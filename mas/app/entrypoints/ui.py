from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.config import load_settings


class ChatRequest(BaseModel):
    namespace: str = "argocd"
    prompt: str


settings = load_settings()
app = FastAPI(title="MAS UI", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "agent_role": settings.agent_role,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MAS UI</title>
  <style>
    :root { color-scheme: light; font-family: Arial, sans-serif; }
    body { margin: 0; background: #f6f8fb; color: #172033; }
    main { max-width: 960px; margin: 0 auto; padding: 32px 20px; }
    h1 { font-size: 24px; margin: 0 0 20px; }
    label { display: block; font-weight: 700; margin: 16px 0 8px; }
    input, textarea, button { box-sizing: border-box; width: 100%; font: inherit; }
    input, textarea {
      border: 1px solid #ccd5e1; border-radius: 6px; padding: 12px;
      background: #fff; color: #172033;
    }
    textarea { min-height: 140px; resize: vertical; }
    button {
      margin-top: 16px; border: 0; border-radius: 6px; padding: 12px 16px;
      background: #2563eb; color: #fff; font-weight: 700; cursor: pointer;
    }
    button:disabled { background: #8aa8e8; cursor: wait; }
    pre {
      margin-top: 20px; padding: 16px; background: #0f172a; color: #dbeafe;
      border-radius: 6px; overflow: auto; min-height: 220px; white-space: pre-wrap;
    }
  </style>
</head>
<body>
  <main>
    <h1>MAS Kubernetes 리소스 분석</h1>
    <label for="namespace">Namespace</label>
    <input id="namespace" value="argocd" />
    <label for="prompt">Prompt</label>
    <textarea id="prompt">Kubernetes 리소스 상태를 분석하고, 문제가 있으면 원인과 다음 확인 작업을 알려줘.</textarea>
    <button id="run">분석 요청</button>
    <pre id="result">분석 결과가 여기에 표시됩니다.</pre>
  </main>
  <script>
    const run = document.getElementById("run");
    const result = document.getElementById("result");
    run.addEventListener("click", async () => {
      run.disabled = true;
      result.textContent = "분석 요청 중...";
      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            namespace: document.getElementById("namespace").value,
            prompt: document.getElementById("prompt").value
          })
        });
        const data = await response.json();
        result.textContent = JSON.stringify(data, null, 2);
      } catch (error) {
        result.textContent = String(error);
      } finally {
        run.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    orchestrator_url = settings.orchestrator_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{orchestrator_url}/analyze",
                json={
                    "namespace": request.namespace,
                    "prompt": request.prompt,
                },
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
