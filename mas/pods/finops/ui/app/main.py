import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


ORCHESTRATOR_URL = os.getenv(
    "ORCHESTRATOR_URL",
    "http://finops-orchestrator.finops-mas.svc.cluster.local",
)

app = FastAPI(title="FinOps UI Agent", version="0.2.0")


class ChatRequest(BaseModel):
    message: str
    event_id: str = "fomc-briefing"


class ApprovalRequest(BaseModel):
    approved_by: str = "operator"
    decision: str = "approved"


def call_orchestrator(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = Request(f"{ORCHESTRATOR_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise HTTPException(status_code=503, detail=f"orchestrator unavailable: {exc}") from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    workflows = call_orchestrator("/api/workflows")
    calendar = call_orchestrator("/api/calendar")
    active = workflows[0] if workflows else None
    return {
        "scenario": "finops",
        "agent": "ui",
        "namespace": "finops-mas",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calendar": calendar,
        "active_workflow": active,
    }


@app.get("/api/calendar")
def calendar() -> Any:
    return call_orchestrator("/api/calendar")


@app.post("/api/workflows/run")
def run_workflow() -> Any:
    return call_orchestrator("/api/workflows/run", method="POST")


@app.get("/api/workflows")
def workflows() -> Any:
    return call_orchestrator("/api/workflows")


@app.get("/api/workflows/{workflow_id}")
def workflow_detail(workflow_id: str) -> Any:
    return call_orchestrator(f"/api/workflows/{workflow_id}")


@app.post("/api/workflows/{workflow_id}/approve")
def approve(workflow_id: str, request: ApprovalRequest) -> Any:
    return call_orchestrator(
        f"/api/workflows/{workflow_id}/approve",
        method="POST",
        body=request.model_dump(),
    )


@app.post("/api/chat")
def chat(request: ChatRequest) -> Any:
    return call_orchestrator("/api/chat", method="POST", body=request.model_dump())


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>FinOps MAS Control</title>
    <style>
      :root {
        color-scheme: light;
        --bg: #f7f9fc;
        --panel: #ffffff;
        --line: #d8e0ea;
        --text: #172033;
        --muted: #64748b;
        --accent: #2563eb;
        --ok: #12805c;
        --warn: #b45309;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Arial, sans-serif;
        background: var(--bg);
        color: var(--text);
      }
      header {
        padding: 18px 24px;
        border-bottom: 1px solid var(--line);
        background: var(--panel);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
      }
      h1, h2, h3 { margin: 0; }
      h1 { font-size: 22px; }
      h2 { font-size: 16px; }
      h3 { font-size: 14px; }
      main {
        max-width: 1220px;
        margin: 0 auto;
        padding: 20px;
        display: grid;
        grid-template-columns: 340px 1fr;
        gap: 16px;
      }
      section, .card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 16px;
      }
      .stack { display: grid; gap: 12px; }
      .row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }
      .muted { color: var(--muted); }
      .metric {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
      }
      .metric .card { padding: 14px; }
      .value { font-size: 24px; font-weight: 700; margin-top: 6px; }
      button {
        border: 0;
        border-radius: 6px;
        background: var(--accent);
        color: #fff;
        font-weight: 700;
        padding: 10px 14px;
        cursor: pointer;
      }
      button.secondary { background: #e2e8f0; color: #172033; }
      button:disabled { opacity: .55; cursor: not-allowed; }
      .timeline {
        display: grid;
        gap: 8px;
      }
      .phase {
        display: grid;
        grid-template-columns: 48px 1fr auto;
        gap: 10px;
        align-items: start;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 10px;
      }
      .badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        padding: 4px 8px;
        background: #e0f2fe;
        color: #075985;
        font-size: 12px;
        font-weight: 700;
      }
      pre {
        margin: 8px 0 0;
        white-space: pre-wrap;
        word-break: break-word;
        color: var(--muted);
        font-size: 12px;
      }
      textarea {
        width: 100%;
        min-height: 80px;
        resize: vertical;
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 10px;
        font: inherit;
      }
      #toast { color: var(--warn); font-size: 13px; }
      @media (max-width: 900px) {
        main { grid-template-columns: 1fr; }
        .metric { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
    </style>
  </head>
  <body>
    <header>
      <div>
        <h1>FinOps MAS Control</h1>
        <div class="muted">Demand shaping first, infrastructure second.</div>
      </div>
      <button onclick="runPlan()">Run FinOps Plan</button>
    </header>
    <main>
      <div class="stack">
        <section>
          <div class="row">
            <h2>Business Calendar</h2>
            <span class="badge">Today</span>
          </div>
          <div id="calendar" class="stack" style="margin-top: 12px;"></div>
        </section>
        <section>
          <h2>ChatOps</h2>
          <p class="muted">Try: spread general users over 20 minutes</p>
          <textarea id="chat-message">Spread general users over 20 minutes</textarea>
          <div class="row" style="margin-top: 10px;">
            <button class="secondary" onclick="sendChat()">Send Change Request</button>
          </div>
          <pre id="chat-result"></pre>
        </section>
      </div>
      <div class="stack">
        <section>
          <div class="row">
            <h2>Final Plan</h2>
            <div id="status" class="badge">idle</div>
          </div>
          <div class="metric" style="margin-top: 12px;">
            <div class="card"><div class="muted">Before Peak</div><div id="before" class="value">-</div></div>
            <div class="card"><div class="muted">After Peak</div><div id="after" class="value">-</div></div>
            <div class="card"><div class="muted">Required Pods</div><div id="pods" class="value">-</div></div>
            <div class="card"><div class="muted">Cost</div><div id="cost" class="value">-</div></div>
          </div>
          <div class="row" style="margin-top: 12px;">
            <div id="toast"></div>
            <button id="approve" onclick="approvePlan()" disabled>Approve Dry-run</button>
          </div>
        </section>
        <section>
          <h2>Workflow Timeline</h2>
          <div id="timeline" class="timeline" style="margin-top: 12px;"></div>
        </section>
      </div>
    </main>
    <script>
      let currentWorkflow = null;

      async function api(path, options = {}) {
        const res = await fetch(path, {
          headers: {"Content-Type": "application/json"},
          ...options
        });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
      }

      function showError(error) {
        document.getElementById("toast").textContent = error.message || String(error);
      }

      async function loadDashboard() {
        try {
          const data = await api("/api/dashboard");
          renderCalendar(data.calendar || []);
          if (data.active_workflow) {
            currentWorkflow = data.active_workflow.workflow_id;
            await loadWorkflow(currentWorkflow);
          }
        } catch (error) {
          showError(error);
        }
      }

      function renderCalendar(items) {
        const el = document.getElementById("calendar");
        if (!items.length) {
          el.innerHTML = '<div class="muted">No business events found.</div>';
          return;
        }
        el.innerHTML = items.map(item => `
          <div class="card">
            <div class="row"><h3>${item.title}</h3><span class="badge">Grade ${item.grade}</span></div>
            <div class="muted" style="margin-top: 8px;">${item.scheduled_at} · ${item.target_users.toLocaleString()} users · delay ${item.max_delay_minutes}m</div>
          </div>
        `).join("");
      }

      async function runPlan() {
        try {
          document.getElementById("toast").textContent = "Running mock Temporal workflow...";
          const result = await api("/api/workflows/run", {method: "POST"});
          currentWorkflow = result.workflow_id;
          await loadWorkflow(currentWorkflow);
          document.getElementById("toast").textContent = "";
        } catch (error) {
          showError(error);
        }
      }

      async function loadWorkflow(workflowId) {
        const data = await api(`/api/workflows/${workflowId}`);
        renderPlan(data);
        renderTimeline(data.timeline || []);
      }

      function renderPlan(data) {
        const plan = data.plan || {};
        document.getElementById("status").textContent = data.status || "unknown";
        document.getElementById("before").textContent = plan.peak_rps_before ? `${plan.peak_rps_before} rps` : "-";
        document.getElementById("after").textContent = plan.peak_rps_after ? `${plan.peak_rps_after} rps` : "-";
        document.getElementById("pods").textContent = plan.required_app_pods || "-";
        document.getElementById("cost").textContent = plan.estimated_cost_usd ? `$${plan.estimated_cost_usd}` : "-";
        document.getElementById("approve").disabled = data.status !== "waiting_approval";
      }

      function renderTimeline(items) {
        const el = document.getElementById("timeline");
        el.innerHTML = items.map(item => `
          <div class="phase">
            <span class="badge">${item.phase}</span>
            <div>
              <strong>${item.agent}</strong>
              <pre>${JSON.stringify(item.result, null, 2)}</pre>
            </div>
            <span class="badge">${item.status}</span>
          </div>
        `).join("");
      }

      async function approvePlan() {
        if (!currentWorkflow) return;
        try {
          await api(`/api/workflows/${currentWorkflow}/approve`, {
            method: "POST",
            body: JSON.stringify({approved_by: "operator", decision: "approved"})
          });
          await loadWorkflow(currentWorkflow);
        } catch (error) {
          showError(error);
        }
      }

      async function sendChat() {
        try {
          const message = document.getElementById("chat-message").value;
          const data = await api("/api/chat", {
            method: "POST",
            body: JSON.stringify({event_id: "fomc-briefing", message})
          });
          document.getElementById("chat-result").textContent = JSON.stringify(data, null, 2);
        } catch (error) {
          showError(error);
        }
      }

      loadDashboard();
    </script>
  </body>
</html>
"""
