import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


ORCHESTRATOR_URL = os.getenv(
    "ORCHESTRATOR_URL",
    "http://aiops-orchestrator.aiops-mas.svc.cluster.local",
)
ORCHESTRATOR_TIMEOUT_SECONDS = int(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "30"))
TEMPORAL_UI_URL = os.getenv(
    "TEMPORAL_UI_URL",
    "https://temporal-ui.teleport.local",
)

app = FastAPI(title="AIOps MAS Control", version="0.1.0")


class RunWorkflowRequest(BaseModel):
    cluster_name: str
    namespace: str
    workflow_id: str | None = None


def call_orchestrator(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = Request(f"{ORCHESTRATOR_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=ORCHESTRATOR_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"orchestrator timeout: {exc}") from exc
    except URLError as exc:
        raise HTTPException(status_code=503, detail=f"orchestrator unavailable: {exc}") from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard() -> Any:
    return call_orchestrator("/api/dashboard")


@app.post("/api/workflows/run")
def run_workflow(request: RunWorkflowRequest) -> Any:
    return call_orchestrator(
        "/api/workflows/run",
        method="POST",
        body=request.model_dump(),
    )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return f"""
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>AIOps MAS Control</title>
    <style>
      :root {{
        --bg: #f7f9fc;
        --panel: #ffffff;
        --line: #d8e0ea;
        --text: #172033;
        --muted: #68758c;
        --blue: #4d65f4;
        --blue-soft: #eaf0ff;
        --green: #108a57;
        --red: #c53b3b;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--bg);
        color: var(--text);
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 18px 22px;
        border-bottom: 1px solid var(--line);
        background: var(--panel);
      }}
      h1 {{ margin: 0; font-size: 24px; line-height: 1.1; }}
      .sub {{ color: var(--muted); margin-top: 3px; }}
      main {{ padding: 18px; display: grid; gap: 18px; }}
      .summary {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
      }}
      .card {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 16px;
      }}
      .label {{ color: var(--muted); font-size: 14px; margin-bottom: 8px; }}
      .value {{ font-size: 24px; font-weight: 800; }}
      .layout {{
        display: grid;
        grid-template-columns: 420px minmax(0, 1fr);
        gap: 18px;
      }}
      .panel {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 18px;
      }}
      h2 {{ font-size: 18px; margin: 0 0 14px; }}
      label {{ display: block; font-weight: 700; margin: 14px 0 6px; }}
      select, input, textarea {{
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 11px 12px;
        background: #fff;
        color: var(--text);
        font: inherit;
      }}
      button {{
        border: 0;
        border-radius: 8px;
        padding: 12px 16px;
        background: var(--blue);
        color: white;
        font-weight: 800;
        cursor: pointer;
      }}
      button:disabled {{ cursor: not-allowed; opacity: 0.55; }}
      .actions {{ display: flex; gap: 10px; margin-top: 18px; }}
      .secondary {{ background: #e8edf6; color: var(--text); }}
      .timeline {{ display: grid; gap: 10px; }}
      .step {{
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 13px 14px;
        display: flex;
        justify-content: space-between;
        gap: 14px;
      }}
      .badge {{
        align-self: start;
        border-radius: 999px;
        padding: 4px 9px;
        background: var(--blue-soft);
        color: #3150b8;
        font-size: 12px;
        font-weight: 800;
        white-space: nowrap;
      }}
      .result {{
        min-height: 128px;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px;
        background: #fbfdff;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }}
      .ok {{ color: var(--green); }}
      .err {{ color: var(--red); }}
      a {{ color: #3150b8; font-weight: 700; text-decoration: none; }}
      @media (max-width: 900px) {{
        .summary, .layout {{ grid-template-columns: 1fr; }}
        header {{ align-items: flex-start; flex-direction: column; }}
      }}
    </style>
  </head>
  <body>
    <header>
      <div>
        <h1>AIOps MAS Control</h1>
        <div class="sub">Incident detection first, remediation after approval.</div>
      </div>
      <button id="refreshButton" class="secondary">새로고침</button>
    </header>
    <main>
      <section class="summary">
        <div class="card">
          <div class="label">상태</div>
          <div id="statusValue" class="value">-</div>
        </div>
        <div class="card">
          <div class="label">대상 Cluster</div>
          <div id="clusterValue" class="value">-</div>
        </div>
        <div class="card">
          <div class="label">Namespace</div>
          <div id="namespaceValue" class="value">-</div>
        </div>
        <div class="card">
          <div class="label">Task Queue</div>
          <div id="queueValue" class="value">-</div>
        </div>
      </section>

      <section class="layout">
        <div class="panel">
          <h2>수동 실행</h2>
          <label for="targetSelect">대상</label>
          <select id="targetSelect">
            <option value="financial-service-eks|stock-demo">financial-service-eks / stock-demo</option>
            <option value="financial-ops-eks|tetragon">financial-ops-eks / tetragon</option>
          </select>
          <label for="workflowId">Workflow ID</label>
          <input id="workflowId" placeholder="비워두면 자동 생성" />
          <div class="actions">
            <button id="runButton">AIOps 실행</button>
            <button id="clearButton" class="secondary">결과 지우기</button>
          </div>
        </div>

        <div class="panel">
          <h2>AIOps 진행 흐름</h2>
          <div class="timeline">
            <div class="step"><span>Detect: 대상 namespace에서 이상 pod 탐지</span><span class="badge">read</span></div>
            <div class="step"><span>Analyze: 원인과 복구 전략 생성</span><span class="badge">plan</span></div>
            <div class="step"><span>HITL: Slack 승인 후 execute 진행</span><span class="badge">approval</span></div>
            <div class="step"><span>Execute: restart / HPA patch / rollback 수행</span><span class="badge">change</span></div>
            <div class="step"><span>Verify: 복구 여부 확인</span><span class="badge">check</span></div>
          </div>
        </div>
      </section>

      <section class="panel">
        <h2>실행 결과</h2>
        <div id="resultBox" class="result">아직 실행된 워크플로우가 없습니다.</div>
      </section>
    </main>
    <script>
      const temporalUrl = {json.dumps(TEMPORAL_UI_URL)};
      const statusValue = document.getElementById("statusValue");
      const clusterValue = document.getElementById("clusterValue");
      const namespaceValue = document.getElementById("namespaceValue");
      const queueValue = document.getElementById("queueValue");
      const targetSelect = document.getElementById("targetSelect");
      const workflowId = document.getElementById("workflowId");
      const resultBox = document.getElementById("resultBox");
      const runButton = document.getElementById("runButton");

      function selectedTarget() {{
        const [cluster_name, namespace] = targetSelect.value.split("|");
        return {{ cluster_name, namespace }};
      }}

      function syncTargetCards() {{
        const target = selectedTarget();
        clusterValue.textContent = target.cluster_name;
        namespaceValue.textContent = target.namespace;
      }}

      async function refreshDashboard() {{
        syncTargetCards();
        try {{
          const response = await fetch("/api/dashboard");
          if (!response.ok) throw new Error(await response.text());
          const data = await response.json();
          statusValue.textContent = "ready";
          statusValue.className = "value ok";
          queueValue.textContent = data.task_queue || "-";
        }} catch (error) {{
          statusValue.textContent = "error";
          statusValue.className = "value err";
          queueValue.textContent = "-";
          resultBox.textContent = `dashboard error: ${{error}}`;
        }}
      }}

      async function runWorkflow() {{
        const target = selectedTarget();
        runButton.disabled = true;
        resultBox.textContent = "AIOps workflow를 시작하는 중입니다...";
        try {{
          const body = {{
            ...target,
            workflow_id: workflowId.value.trim() || null,
          }};
          const response = await fetch("/api/workflows/run", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(body),
          }});
          if (!response.ok) throw new Error(await response.text());
          const data = await response.json();
          const workflowLink = `${{temporalUrl}}/namespaces/default/workflows/${{data.workflow_id}}`;
          resultBox.innerHTML =
            `workflow_id: <a href="${{workflowLink}}" target="_blank" rel="noreferrer">${{data.workflow_id}}</a>\\n` +
            `cluster: ${{data.cluster_name}}\\n` +
            `namespace: ${{data.namespace}}\\n` +
            `task_queue: ${{data.task_queue}}`;
        }} catch (error) {{
          resultBox.textContent = `run error: ${{error}}`;
        }} finally {{
          runButton.disabled = false;
        }}
      }}

      targetSelect.addEventListener("change", syncTargetCards);
      document.getElementById("refreshButton").addEventListener("click", refreshDashboard);
      document.getElementById("clearButton").addEventListener("click", () => {{
        resultBox.textContent = "아직 실행된 워크플로우가 없습니다.";
      }});
      runButton.addEventListener("click", runWorkflow);
      refreshDashboard();
    </script>
  </body>
</html>
"""
