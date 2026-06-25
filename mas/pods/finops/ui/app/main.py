import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


ORCHESTRATOR_URL = os.getenv(
    "ORCHESTRATOR_URL",
    "http://finops-orchestrator.finops-mas.svc.cluster.local",
)

app = FastAPI(title="FinOps UI Agent", version="0.4.0")


class ChatRequest(BaseModel):
    message: str
    workflow_id: str | None = None
    conversation_history: list[dict[str, Any]] = []


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
    calendar = call_orchestrator("/api/events")
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


@app.get("/api/events")
def events() -> Any:
    return call_orchestrator("/api/events")


@app.post("/api/workflows/run")
def run_workflow(event_id: str = "fomc-briefing") -> Any:
    return call_orchestrator(
        f"/api/workflows/run?event_id={quote(event_id)}",
        method="POST",
    )


@app.get("/api/workflows")
def workflows() -> Any:
    return call_orchestrator("/api/workflows")


@app.get("/api/workflows/{workflow_id}")
def workflow_detail(workflow_id: str) -> Any:
    return call_orchestrator(f"/api/workflows/{workflow_id}")


@app.get("/api/workflows/{workflow_id}/agents")
def workflow_agents(workflow_id: str) -> Any:
    return call_orchestrator(f"/api/workflows/{workflow_id}/agents")


@app.get("/api/workflows/{workflow_id}/broker-log")
def workflow_broker_log(workflow_id: str) -> Any:
    return call_orchestrator(f"/api/workflows/{workflow_id}/broker-log")


@app.get("/api/executions/{execution_workflow_id}")
def execution_detail(execution_workflow_id: str) -> Any:
    return call_orchestrator(f"/api/executions/{execution_workflow_id}")


@app.get("/api/workflows/{workflow_id}/execution")
def workflow_execution(workflow_id: str) -> Any:
    return call_orchestrator(f"/api/workflows/{workflow_id}/execution")


@app.post("/api/workflows/{workflow_id}/retry")
def retry_workflow(workflow_id: str) -> Any:
    return call_orchestrator(
        f"/api/workflows/{workflow_id}/retry",
        method="POST",
    )


@app.post("/api/workflows/{workflow_id}/replan")
def replan_workflow(workflow_id: str, intent: dict[str, Any]) -> Any:
    return call_orchestrator(
        f"/api/workflows/{workflow_id}/replan",
        method="POST",
        body=intent,
    )


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
        --bg: #f7f9fc;
        --panel: #fff;
        --line: #d8e0ea;
        --text: #172033;
        --muted: #64748b;
        --accent: #2563eb;
        --accent-soft: #dbeafe;
        --warn: #b45309;
      }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Arial, sans-serif; background: var(--bg); color: var(--text); }
      header {
        padding: 16px 22px;
        border-bottom: 1px solid var(--line);
        background: var(--panel);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
      }
      h1, h2, h3 { margin: 0; }
      h1 { font-size: 22px; }
      h2 { font-size: 16px; }
      h3 { font-size: 14px; }
      main {
        width: 100%;
        margin: 0;
        padding: 16px;
        display: grid;
        grid-template-columns: 1fr;
        gap: 16px;
      }
      section, .card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px;
      }
      .stack { display: grid; gap: 12px; }
      .summary {
        display: grid;
        grid-template-columns: auto 1fr auto;
        gap: 16px;
        align-items: center;
      }
      .content-grid {
        display: grid;
        grid-template-columns: minmax(560px, 34vw) minmax(0, 1fr);
        gap: 16px;
        align-items: start;
      }
      .row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
      .muted { color: var(--muted); }
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
      button {
        border: 0;
        border-radius: 6px;
        background: var(--accent);
        color: #fff;
        font-weight: 700;
        padding: 10px 14px;
        cursor: pointer;
      }
      button.secondary { background: #e2e8f0; color: var(--text); }
      button:disabled { opacity: .55; cursor: not-allowed; }
      textarea {
        width: 100%;
        min-height: 82px;
        resize: vertical;
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 10px;
        font: inherit;
      }
      .calendar-grid {
        display: grid;
        grid-template-columns: repeat(7, minmax(0, 1fr));
        gap: 8px;
        margin-top: 12px;
      }
      .day-name { color: var(--muted); font-size: 11px; font-weight: 700; text-align: center; }
      .day {
        min-height: 118px;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 8px;
        background: #fff;
      }
      .day.empty {
        border-color: transparent;
        background: transparent;
      }
      .day.today { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
      .date-number { font-size: 12px; font-weight: 700; }
      .event-pill {
        margin-top: 6px;
        border-radius: 6px;
        background: var(--accent-soft);
        color: #1e3a8a;
        padding: 7px;
        font-size: 12px;
        line-height: 1.25;
        font-weight: 700;
        white-space: normal;
        overflow-wrap: break-word;
      }
      .chat-room {
        min-height: 620px;
        max-height: calc(100vh - 332px);
        overflow: auto;
        display: grid;
        gap: 10px;
        align-content: start;
        padding-right: 4px;
      }
      .bubble {
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 12px;
        background: #fff;
      }
      .bubble.operator {
        margin-left: 48px;
        background: #eff6ff;
        border-color: #bfdbfe;
      }
      .bubble.agent { margin-right: 48px; }
      .speaker { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-weight: 700; }
      .bubble p { margin: 8px 0 0; color: #334155; line-height: 1.45; }
      .metric { display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 10px; }
      .metric .card { padding: 12px; }
      .value { font-size: 23px; font-weight: 700; margin-top: 6px; }
      pre {
        margin: 8px 0 0;
        white-space: pre-wrap;
        word-break: break-word;
        color: var(--muted);
        font-size: 12px;
      }
      .report-lead {
        margin: 12px 0 0;
        max-width: 1000px;
        color: #334155;
        line-height: 1.55;
      }
      .report-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 20px;
        margin-top: 18px;
      }
      .report-group {
        border-top: 2px solid var(--line);
        padding-top: 12px;
        min-width: 0;
      }
      .report-kv {
        display: grid;
        grid-template-columns: minmax(120px, 1fr) minmax(0, 1.4fr);
        gap: 8px 12px;
        margin: 12px 0 0;
        font-size: 13px;
      }
      .report-kv dt { color: var(--muted); }
      .report-kv dd { margin: 0; font-weight: 700; overflow-wrap: anywhere; }
      .source-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
      .source-list .badge { border-radius: 4px; font-weight: 600; }
      .report-json {
        max-height: 190px;
        overflow: auto;
        padding: 8px;
        background: #f8fafc;
        border: 1px solid var(--line);
        border-radius: 6px;
      }
      #toast { color: var(--warn); font-size: 13px; }
      .toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
      select { padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: white; }
      .agent-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 10px; margin-top: 12px; }
      .agent-card { border: 1px solid var(--line); border-radius: 10px; padding: 12px; cursor: pointer; background: white; }
      .agent-card:hover { border-color: var(--accent); }
      .status-completed { background: #dcfce7; color: #166534; }
      .status-needs_data { background: #fef3c7; color: #92400e; }
      .status-blocked, .status-failed { background: #fee2e2; color: #991b1b; }
      .status-requires_review { background: #ffedd5; color: #9a3412; }
      .status-running { background: #dbeafe; color: #1d4ed8; }
      .status-success { background: #dcfce7; color: #166534; }
      .status-pending { background: #f1f5f9; color: #475569; }
      .status-skipped { background: #f1f5f9; color: #475569; }
      .candidate-table { width: 100%; border-collapse: collapse; margin-top: 12px; }
      .candidate-table th, .candidate-table td { padding: 9px; border-bottom: 1px solid var(--line); text-align: left; }
      .candidate-table tr.recommended { background: #ecfdf5; font-weight: 700; }
      .issue { color: #b91c1c; }
      .warning { color: #b45309; }
      .broker-flow { padding: 8px 0; border-bottom: 1px solid var(--line); }
      .modal { position: fixed; inset: 0; background: rgba(15, 23, 42, .55); display: grid; place-items: center; z-index: 10; }
      .modal[hidden] { display: none; }
      .modal-panel { background: white; width: min(900px, 92vw); max-height: 88vh; overflow: auto; border-radius: 12px; padding: 18px; }
      .modal pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f8fafc; padding: 10px; border-radius: 8px; }
      @media (max-width: 1020px) {
        .summary { grid-template-columns: 1fr; }
        .content-grid { grid-template-columns: 1fr; }
        .report-grid { grid-template-columns: 1fr; }
        .metric { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .chat-room { max-height: none; }
        .day { min-height: 104px; }
      }
    </style>
  </head>
  <body>
    <header>
      <div>
        <h1>FinOps MAS Control</h1>
        <div class="muted">Demand shaping first, infrastructure second.</div>
      </div>
      <div class="toolbar">
        <select id="event-select" aria-label="FinOps test scenario"></select>
        <button onclick="runPlan()">Run FinOps Plan</button>
        <button id="retry" class="secondary" onclick="retryPlan()" disabled>Retry Workflow</button>
      </div>
    </header>
    <main>
      <section>
        <div class="summary">
          <div>
            <h2>Final Plan</h2>
            <div id="status" class="badge" style="margin-top: 8px;">idle</div>
          </div>
          <div class="metric">
            <div class="card"><div class="muted">Before Peak</div><div id="before" class="value">-</div></div>
            <div class="card"><div class="muted">After Peak</div><div id="after" class="value">-</div></div>
            <div class="card"><div class="muted">Required Pods</div><div id="pods" class="value">-</div></div>
            <div class="card"><div class="muted">Cost</div><div id="cost" class="value">-</div></div>
          </div>
          <button id="approve" onclick="approvePlan()" disabled>Approve Dry-run</button>
        </div>
      </section>

      <div class="content-grid">
        <section>
          <div class="row">
            <h2>Business Calendar</h2>
            <span id="calendar-month" class="badge">Month</span>
          </div>
          <div id="calendar" class="calendar-grid"></div>
        </section>

        <div class="stack">
          <section>
            <div class="row">
              <h2>Agent Chat</h2>
              <span id="conversation-status" class="badge">idle</span>
            </div>
            <div id="agent-chat" class="chat-room" style="margin-top: 12px;"></div>
          </section>
          <section>
            <h2>ChatOps</h2>
          <p class="muted">완성된 FinOps 보고서에 대해 근거 기반으로 질문합니다. Workflow 변경은 수행하지 않습니다.</p>
          <textarea id="chat-message">왜 Pod가 22개 필요한가?</textarea>
            <div class="row" style="margin-top: 10px;">
              <button id="chat-send" class="secondary" onclick="sendChat()" disabled>Ask Report</button>
              <div id="toast"></div>
            </div>
          </section>
        </div>
      </div>

      <section>
        <div class="row"><h2>Agent Progress</h2><span class="badge">live</span></div>
        <div id="agent-cards" class="agent-grid"></div>
      </section>

      <section>
        <h2>Data Broker Requests</h2>
        <div id="broker-log" class="muted">No broker calls.</div>
      </section>

      <section id="candidate-section" hidden>
        <h2>Plan Candidates</h2>
        <div id="candidate-table"></div>
      </section>

      <section id="quality-section" hidden>
        <h2>Quality Gate</h2>
        <div id="quality-gate"></div>
      </section>

      <section id="execution-section" hidden>
        <div class="row">
          <h2>Event Execution Dry-run</h2>
          <span id="execution-status" class="badge">pending</span>
        </div>
        <div id="execution-steps" class="agent-grid"></div>
      </section>

      <section id="finops-report" hidden>
        <div class="row">
          <h2 id="report-title">FinOps Event Readiness Report</h2>
          <span class="badge">Final report</span>
        </div>
        <p id="report-summary" class="report-lead"></p>
        <div id="report-body" class="report-grid"></div>
      </section>
    </main>
    <div id="agent-modal" class="modal" hidden onclick="closeAgentModal(event)">
      <div class="modal-panel" onclick="event.stopPropagation()">
        <div class="row"><h2 id="modal-agent-name">Agent</h2><button class="secondary" onclick="closeAgentModal()">Close</button></div>
        <div id="modal-agent-body"></div>
      </div>
    </div>
    <script>
      let currentWorkflow = null;
      let calendarItems = [];
      let workflowPoller = null;
      let agentDetails = {};
      let conversationHistory = [];
      let pendingReplan = null;
      let previousWorkflow = null;
      let previousPlanSnapshot = null;
      let currentPlanSnapshot = null;
      let currentExecution = null;
      let executionPoller = null;

      async function api(path, options = {}) {
        const res = await fetch(path, {headers: {"Content-Type": "application/json"}, ...options});
        if (!res.ok) throw new Error(await res.text());
        return res.json();
      }

      function showError(error) {
        document.getElementById("toast").textContent = error.message || String(error);
      }

      async function loadDashboard() {
        try {
          const data = await api("/api/dashboard");
          calendarItems = data.calendar || [];
          const select = document.getElementById("event-select");
          select.innerHTML = calendarItems.map(item => `
            <option value="${escapeHtml(item.event_id)}">${escapeHtml(item.event_id)} · ${escapeHtml(item.title)}</option>
          `).join("");
          renderCalendar(calendarItems);
          if (data.active_workflow) {
            if (calendarItems.some(item => item.event_id === data.active_workflow.event_id)) {
              select.value = data.active_workflow.event_id;
            }
            currentWorkflow = data.active_workflow.workflow_id;
            const done = await loadWorkflow(currentWorkflow);
            if (!done) startWorkflowPolling(currentWorkflow);
          } else {
            renderEmptyConversation();
          }
        } catch (error) {
          showError(error);
        }
      }

      function renderCalendar(items) {
        const el = document.getElementById("calendar");
        const now = new Date();
        const year = now.getFullYear();
        const month = now.getMonth();
        document.getElementById("calendar-month").textContent =
          now.toLocaleString("en", {month: "short", year: "numeric"});
        const first = new Date(year, month, 1);
        const last = new Date(year, month + 1, 0);
        const names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        const headers = names.map(name => `<div class="day-name">${name}</div>`).join("");
        const days = [];
        for (let i = 0; i < first.getDay(); i++) {
          days.push('<div class="day empty"></div>');
        }
        for (let day = 1; day <= last.getDate(); day++) {
          const date = new Date(year, month, day);
          const isToday = date.toDateString() === now.toDateString();
          const events = isToday ? items.map(item => `
            <div class="event-pill">${item.title}<br>${item.scheduled_at} / Grade ${item.grade}</div>
          `).join("") : "";
          days.push(`
            <div class="day ${isToday ? "today" : ""}">
              <div class="date-number">${day}</div>${events}
            </div>
          `);
        }
        el.innerHTML = headers + days.join("");
      }

      async function runPlan() {
        try {
          document.getElementById("toast").textContent = "Running FinOps plan...";
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
        renderConversation(data);
      }

      function renderPlan(data) {
        const plan = data.plan || {};
        currentPlanSnapshot = plan;
        document.getElementById("status").textContent = data.status || "unknown";
        document.getElementById("before").textContent = plan.peak_rps_before ? `${plan.peak_rps_before} rps` : "-";
        document.getElementById("after").textContent = plan.peak_rps_after ? `${plan.peak_rps_after} rps` : "-";
        document.getElementById("pods").textContent = plan.required_app_pods || "-";
        document.getElementById("cost").textContent = plan.estimated_cost_usd ? `$${plan.estimated_cost_usd}` : "-";
        document.getElementById("approve").disabled = !["waiting_approval", "plan_ready"].includes(data.status);
        document.getElementById("retry").disabled = !currentWorkflow;
        renderCandidates(data.plan_candidates || plan.plan_candidates || [], data.recommended_candidate || plan.recommended_candidate);
        renderPlanComparison(data.plan_candidates || plan.plan_candidates || []);
        renderQualityGate(data.quality_gate_result || plan.quality_gate_result || {});
        renderReport(plan.report);
      }

      function renderCandidates(candidates, recommended) {
        const section = document.getElementById("candidate-section");
        if (!candidates.length) { section.hidden = true; return; }
        section.hidden = false;
        const recommendedLabel = recommended && recommended.label;
        document.getElementById("candidate-table").innerHTML = `
          <table class="candidate-table">
            <thead><tr><th>후보</th><th>Push 분산</th><th>Pod</th><th>예상 비용</th><th>예상 p95</th><th>위험도</th><th>점수</th><th>추천</th></tr></thead>
            <tbody>${candidates.map(item => `
              <tr class="${item.label === recommendedLabel ? "recommended" : ""}">
                <td>${escapeHtml(item.label)}</td><td>${item.push_window_minutes}분</td>
                <td>${item.required_pods}</td><td>$${Number(item.estimated_cost_usd).toFixed(2)}</td>
                <td>${item.estimated_p95_ms}ms</td><td>${escapeHtml(item.risk_level)}</td>
                <td>${Number(item.score).toFixed(4)}</td><td>${item.label === recommendedLabel ? "★" : ""}</td>
              </tr>`).join("")}</tbody>
          </table>`;
      }

      function renderQualityGate(gate) {
        const section = document.getElementById("quality-section");
        if (!Object.keys(gate).length) { section.hidden = true; return; }
        section.hidden = false;
        document.getElementById("quality-gate").innerHTML = `
          <p><strong>${gate.passed ? "✓ 통과" : "✗ 실패"}</strong></p>
          <ul class="issue">${(gate.issues || []).map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
          <ul class="warning">${(gate.warnings || []).map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
      }

      function renderPlanComparison(currentCandidates) {
        const previousCandidates = previousPlanSnapshot?.plan_candidates || [];
        if (!previousCandidates.length || !currentCandidates.length) return;
        const rows = (items) => items.map(item => `
          <tr>
            <td>${escapeHtml(item.label)}</td>
            <td>${item.push_window_minutes}분</td>
            <td>${item.required_pods}</td>
            <td>$${Number(item.estimated_cost_usd).toFixed(2)}</td>
            <td>${item.estimated_p95_ms}ms</td>
            <td>${escapeHtml(item.risk_level)}</td>
            <td>${Number(item.score).toFixed(4)}</td>
          </tr>
        `).join("");
        document.getElementById("candidate-table").innerHTML += `
          <h3>Previous Plan Candidates</h3>
          <p class="muted">Previous workflow: ${escapeHtml(previousWorkflow || "-")}</p>
          <table class="candidate-table">
            <thead><tr><th>후보</th><th>Push 분산</th><th>Pod</th><th>예상 비용</th><th>예상 p95</th><th>위험</th><th>점수</th></tr></thead>
            <tbody>${rows(previousCandidates)}</tbody>
          </table>
          <h3>New Plan Candidates</h3>
          <table class="candidate-table">
            <thead><tr><th>후보</th><th>Push 분산</th><th>Pod</th><th>예상 비용</th><th>예상 p95</th><th>위험</th><th>점수</th></tr></thead>
            <tbody>${rows(currentCandidates)}</tbody>
          </table>
        `;
      }

      function reportValue(value) {
        if (value === null || value === undefined || value === "") return "-";
        if (Array.isArray(value)) return value.length ? value.map(escapeHtml).join(", ") : "-";
        if (typeof value === "object") return escapeHtml(JSON.stringify(value));
        return escapeHtml(value);
      }

      function reportRows(entries) {
        return `<dl class="report-kv">${entries.map(([label, value]) => `
          <dt>${escapeHtml(label)}</dt><dd>${reportValue(value)}</dd>
        `).join("")}</dl>`;
      }

      function reportGroup(title, content) {
        return `<div class="report-group"><h3>${escapeHtml(title)}</h3>${content}</div>`;
      }

      function reportJson(value) {
        if (!value || (typeof value === "object" && !Object.keys(value).length)) return "-";
        return `<pre class="report-json">${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
      }

      function renderReport(report) {
        const section = document.getElementById("finops-report");
        if (!report) {
          section.hidden = true;
          return;
        }
        section.hidden = false;
        document.getElementById("report-title").textContent = report.title || "FinOps Event Readiness Report";
        document.getElementById("report-summary").textContent = report.executive_summary || "";

        const event = report.event || {};
        const collection = report.data_collection || {};
        const sources = collection.sources || {};
        const traffic = report.traffic || {};
        const capacity = report.capacity || {};
        const cost = report.cost || {};
        const policy = report.policy || {};
        const operations = report.operations || {};
        const sourceTags = Object.entries(sources).map(([name, value]) =>
          `<span class="badge">${escapeHtml(name)}: ${reportValue(value)}</span>`
        ).join("");

        document.getElementById("report-body").innerHTML = [
          reportGroup("Event Summary", reportRows([
            ["Event", event.title], ["Event ID", event.event_id], ["Grade", event.grade],
            ["Target users", event.target_users], ["Scheduled", event.scheduled_at]
          ])),
          reportGroup("Data Sources", `<div class="source-list">${sourceTags || "-"}</div>`),
          reportGroup("Traffic Forecast", reportRows([
            ["Peak before", traffic.peak_rps_before], ["Peak after", traffic.peak_rps_after],
            ["Required pods", traffic.required_app_pods], ["Queue depth", traffic.queue_depth],
            ["P95 latency (ms)", traffic.p95_latency_ms]
          ])),
          reportGroup("Capacity Readiness", reportRows([
            ["Target pods", capacity.target_app_pods], ["Current pods", capacity.current_app_pods],
            ["Ready pods", capacity.ready_app_pods], ["Bottleneck", capacity.bottleneck_status],
            ["RDS CPU", capacity.rds_cpu], ["Cache hit ratio", capacity.cache_hit_ratio]
          ])),
          reportGroup("Cost Estimate", reportRows([
            ["Event cost (USD)", cost.estimated_event_cost_usd], ["Month to date (USD)", cost.month_to_date_usd],
            ["CUR month to date", cost.cur_month_to_date_usd], ["Projected monthly", cost.projected_monthly_usd],
            ["Event budget", cost.event_budget_usd]
          ])),
          reportGroup("Policy Validation", reportRows([
            ["Approval required", policy.approval_required], ["Allowed actions", policy.allowed_actions],
            ["Forbidden actions", policy.forbidden_actions], ["Policy version", policy.policy_version]
          ])),
          reportGroup("Operation Plan", reportRows([
            ["Scale out", operations.scale_out_at], ["Prewarm", operations.prewarm_at],
            ["Scale down", operations.scale_down], ["Observer", operations.observer_recommendation]
          ])),
          reportGroup("Fallback Plan", reportJson(operations.fallback)),
          reportGroup("Postmortem Plan", reportJson(operations.postmortem))
        ].join("");
      }

      /* Legacy conversation renderer retained temporarily for compatibility.
      function renderEmptyConversation() {
        document.getElementById("conversation-status").textContent = "waiting";
        document.getElementById("agent-chat").innerHTML = `
          <div class="bubble agent">
            <div class="speaker"><span>Business Control Agent</span><span class="badge">ready</span></div>
            <p>비즈니스 캘린더를 확인했습니다. FinOps 계획을 실행하면 오늘 이벤트에 맞춰 agent들을 순서대로 조율하겠습니다.</p>
          </div>
        `;
      }

      function narrate(item) {
        const r = item.result || {};
        switch (item.agent) {
          case "Business Control Agent":
            return `${r.event_id || "일정 이벤트"}를 확인했고 등급은 ${r.grade || "unknown"}입니다. 실행 전 승인은 ${r.approval_required ? "필요합니다" : "필요하지 않습니다"}.`;
          case "Demand Shaping Agent":
            return `VIP 사용자는 ${r.vip || "우선"} 처리하고 일반 사용자는 ${r.general_users || "분산 구간"}으로 이동하겠습니다. 이 방식으로 피크를 약 ${r.peak_reduction || r.peak_reduction_percent || "의미 있게"} 낮출 수 있습니다.`;
          case "Traffic Forecast Agent":
            return `평탄화 전 예상 피크는 ${r.peak_rps_before || "-"} rps이고, 평탄화 후에는 ${r.peak_rps_after || "-"} rps입니다. 앱 계층은 ${r.required_app_pods || "-"}개 pod를 준비해야 합니다.`;
          case "Bottleneck Capacity Agent":
            return `병목을 확인했습니다. DB CPU는 약 ${r.db_cpu || "-"}, 캐시 hit ratio는 ${r.cache_hit_ratio || "-"}이고 상태는 ${r.status || "unknown"}입니다.`;
          case "Infra Execution Planner":
            return `${r.scale_out_at || "-"}에 scale-out, ${r.prewarm_at || "-"}에 pre-warm을 권장합니다. scale-down은 ${r.scale_down || "실제 관측 트래픽"} 기준으로 진행합니다.`;
          case "Cost Agent":
            return `예상 이벤트 비용은 총 $${r.total || "-"}입니다. EKS $${r.eks || "-"}, 네트워크 $${r.network || "-"}, 로그 $${r.logs || "-"}, push $${r.push || "-"}를 포함합니다.`;
          case "Unit Economics Agent":
            return `예상 비즈니스 가치는 약 $${r.expected_value_usd || "-"}이고 비용 비율은 ${r.cost_ratio || "-"}입니다. override는 ${r.override ? "검토가 필요합니다" : "권장하지 않습니다"}.`;
          case "Policy Guardrail Agent":
            return `정책상 ${(r.allowed || []).join(", ") || "제안 액션"}은 허용됩니다. 운영자 승인은 ${r.approval_required ? "필요합니다" : "필요하지 않습니다"}.`;
          case "Final Plan":
            return `권고사항을 최종 계획으로 정리했고 workflow 상태를 ${r.status || "waiting"}로 설정했습니다.`;
          case "Observer Agent":
            return `실행 중 관측을 준비했습니다. 첫 권고는 ${r.recommendation || "실제 트래픽을 보고 용량을 조정"}입니다.`;
          case "Fallback Planner":
            return "실행이 안전하지 않으면 VIP 발송만 유지하고 일반 사용자는 hold하며 static report fallback을 제공합니다.";
          case "Postmortem Learning Agent":
            return `이벤트 종료 후 예측과 실제 결과를 비교합니다. 프로필 업데이트 상태는 ${r.profile_update || "pending"}입니다.`;
          case "Dry-run Execution":
            return "승인을 확인했습니다. scale-out, pre-warm, push schedule 등록을 dry-run으로 검증했습니다.";
          default:
            return JSON.stringify(r);
        }
      }

      function renderConversation(data) {
        const el = document.getElementById("agent-chat");
        document.getElementById("conversation-status").textContent = data.status || "running";
        const event = calendarItems[0];
        const intro = event ? `
          <div class="bubble operator">
            <div class="speaker"><span>Operator</span><span class="badge">event</span></div>
            <p>${event.scheduled_at}에 예정된 ${event.title} 이벤트의 FinOps 계획을 준비해줘. 대상자는 ${event.target_users.toLocaleString()}명이야.</p>
          </div>
        ` : "";
        const messages = data.conversation && data.conversation.length
          ? data.conversation.map(item => `
            <div class="bubble agent">
              <div class="speaker"><span>${item.sender}</span><span class="badge">to ${item.receiver}</span></div>
              <p>${item.message}</p>
            </div>
          `).join("")
          : (data.timeline || []).map(item => `
          <div class="bubble agent">
            <div class="speaker"><span>${item.agent}</span><span class="badge">${item.status}</span></div>
            <p>${narrate(item)}</p>
          </div>
        `).join("");
        el.innerHTML = intro + messages;
        el.scrollTop = el.scrollHeight;
      }
      */

      async function approvePlan() {
        if (!currentWorkflow) return;
        try {
          const result = await api(`/api/workflows/${currentWorkflow}/approve`, {
            method: "POST",
            body: JSON.stringify({approved_by: "operator", decision: "approved"})
          });
          await loadWorkflow(currentWorkflow);
          if (result.execution_workflow_id) {
            currentExecution = result.execution_workflow_id;
            await loadExecution(currentExecution);
            startExecutionPolling(currentExecution);
          }
        } catch (error) {
          showError(error);
        }
      }

      async function sendChat() {
        try {
          if (!currentWorkflow) {
            document.getElementById("toast").textContent = "먼저 FinOps 분석을 실행해주세요.";
            return;
          }
          const message = document.getElementById("chat-message").value;
          const data = await api("/api/chat", {
            method: "POST",
            body: JSON.stringify({
              workflow_id: currentWorkflow,
              message,
              conversation_history: conversationHistory
            })
          });
          conversationHistory = data.conversation_history || conversationHistory;
          if (data.pending_replan) pendingReplan = data.pending_replan;
          if (data.new_workflow_id) {
            previousWorkflow = currentWorkflow;
            previousPlanSnapshot = currentPlanSnapshot;
            currentWorkflow = data.new_workflow_id;
            conversationHistory = [];
            currentExecution = null;
            stopExecutionPolling();
            document.getElementById("execution-section").hidden = true;
            renderCallingConversation();
            await loadWorkflow(currentWorkflow);
            startWorkflowPolling(currentWorkflow);
            return;
          }
          const el = document.getElementById("agent-chat");
          el.innerHTML += `
            <div class="bubble operator">
              <div class="speaker"><span>Operator</span><span class="badge">question</span></div>
              <p>${escapeHtml(message)}</p>
            </div>
            ${renderChatReply(data)}
          `;
          el.scrollTop = el.scrollHeight;
        } catch (error) {
          const el = document.getElementById("agent-chat");
          el.innerHTML += `
            <div class="bubble agent">
              <div class="speaker"><span>FinOps Report Analyst</span><span class="badge">error</span></div>
              <p>보고서 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.</p>
            </div>
          `;
          showError(error);
        }
      }

      function escapeHtml(value) {
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#039;");
      }

      function updateChatAvailability(status = null) {
        const disabled = !currentWorkflow || ["running", "starting"].includes(status || "");
        const textarea = document.getElementById("chat-message");
        const button = document.getElementById("chat-send");
        if (textarea) textarea.disabled = disabled;
        if (button) button.disabled = disabled;
        if (!currentWorkflow) {
          document.getElementById("conversation-status").textContent = "no workflow";
        }
      }

      function agentLabel(agentKey) {
        const labels = {
          business_control: "Business Control",
          demand_shaping: "Demand Shaping",
          traffic_forecast: "Traffic Forecast",
          bottleneck_capacity: "Bottleneck Capacity",
          infra_execution: "Infra Execution",
          cost: "Cost",
          unit_economics: "Unit Economics",
          policy_guardrail: "Policy Guardrail",
          observer: "Observer",
          fallback: "Fallback",
          postmortem_learning: "Postmortem Learning"
        };
        return labels[agentKey] || agentKey;
      }

      function renderChatReply(data) {
        const sources = (data.sources || []).map(source =>
          `<span class="badge">${escapeHtml(agentLabel(source))}</span>`
        ).join(" ");
        const tools = (data.tools_used || []).length
          ? `<details><summary>Tools used</summary><p>${(data.tools_used || []).map(escapeHtml).join(", ")}</p></details>`
          : "";
        const replanActions = data.pending_replan ? `
          <div class="row" style="margin-top: 10px;">
            <button class="secondary" onclick="confirmPendingReplan()">확인</button>
            <button class="secondary" onclick="cancelPendingReplan()">취소</button>
          </div>` : "";
        return `
          <div class="bubble agent">
            <div class="speaker"><span>FinOps Report Analyst</span><span class="badge">answer</span></div>
            <p>${escapeHtml(data.answer || "보고서 데이터를 불러올 수 없습니다")}</p>
            <div>${sources}</div>
            ${tools}
            ${replanActions}
          </div>
        `;
      }

      async function confirmPendingReplan() {
        if (!currentWorkflow || !pendingReplan) return;
        try {
          previousWorkflow = currentWorkflow;
          previousPlanSnapshot = currentPlanSnapshot;
          const result = await api(`/api/workflows/${currentWorkflow}/replan`, {
            method: "POST",
            body: JSON.stringify(pendingReplan)
          });
          pendingReplan = null;
          conversationHistory = [];
          currentWorkflow = result.new_workflow_id;
          currentExecution = null;
          stopExecutionPolling();
          document.getElementById("execution-section").hidden = true;
          renderCallingConversation();
          await loadWorkflow(currentWorkflow);
          startWorkflowPolling(currentWorkflow);
        } catch (error) {
          showError(error);
        }
      }

      function cancelPendingReplan() {
        pendingReplan = null;
        const el = document.getElementById("agent-chat");
        el.innerHTML += `
          <div class="bubble agent">
            <div class="speaker"><span>FinOps Report Analyst</span><span class="badge">cancelled</span></div>
            <p>재계획 요청을 취소했습니다. 기존 보고서 질의는 계속할 수 있습니다.</p>
          </div>
        `;
      }

      /* Legacy duplicate renderer. The active implementation follows this block.
      function eventIntroBubble(label = "요청") {
        const event = calendarItems[0];
        if (!event) return "";
        const users = Number(event.target_users || 0).toLocaleString();
        return `
          <div class="bubble operator">
            <div class="speaker"><span>Operator</span><span class="badge">event</span></div>
            <p>${escapeHtml(event.scheduled_at)} 예정된 ${escapeHtml(event.title)} 일정으로 FinOps 계획을 ${label}합니다. 대상자는 ${users}명입니다.</p>
          </div>
        `;
      }

      function renderEmptyConversation() {
        document.getElementById("conversation-status").textContent = "ready";
        document.getElementById("agent-chat").innerHTML = `
          <div class="bubble agent">
            <div class="speaker"><span>FinOps MAS</span><span class="badge">ready</span></div>
            <p>아직 agent를 호출하지 않았습니다. Run FinOps Plan을 누르면 일정 확인부터 정책 검증까지 agent 호출과 결과만 순서대로 표시합니다.</p>
          </div>
        `;
      }

      function renderCallingConversation() {
        document.getElementById("conversation-status").textContent = "calling_agents";
        document.getElementById("agent-chat").innerHTML = eventIntroBubble("요청") + `
          <div class="bubble agent">
            <div class="speaker"><span>Orchestrator</span><span class="badge">calling</span></div>
            <p>Temporal workflow를 시작했고, Business Control Agent부터 순서대로 호출하고 있습니다.</p>
          </div>
        `;
      }

      function narrate(item) {
        const r = item.result || {};
        switch (item.agent) {
          case "Business Control Agent":
            return `비즈니스 일정을 확인했습니다. 이벤트 등급은 ${r.grade || "unknown"}이고, 실행 전 승인은 ${r.approval_required ? "필요합니다" : "필요하지 않습니다"}.`;
          case "Demand Shaping Agent":
            return `VIP는 ${r.vip || "즉시"} 처리하고, 일반 사용자는 ${r.general_users || "분산 발송"} 전략으로 낮춥니다. 예상 peak 감소폭은 ${r.peak_reduction || r.peak_reduction_percent || "계산 중"}입니다.`;
          case "Traffic Forecast Agent":
            return `평탄화 전 peak는 ${r.peak_rps_before || "-"} rps, 평탄화 후 peak는 ${r.peak_rps_after || "-"} rps입니다. 필요한 app pod는 ${r.required_app_pods || "-"}개입니다.`;
          case "Bottleneck Capacity Agent":
            return `병목을 확인했습니다. DB CPU는 ${r.db_cpu || "-"}, cache hit ratio는 ${r.cache_hit_ratio || "-"}이고 상태는 ${r.status || "unknown"}입니다.`;
          case "Infra Execution Planner":
            return `${r.scale_out_at || "-"}에 scale-out, ${r.prewarm_at || "-"}에 pre-warm을 권장합니다. scale-down은 ${r.scale_down || "실측 트래픽"} 기준으로 진행합니다.`;
          case "Cost Agent":
            return `예상 이벤트 비용은 총 $${r.total || "-"}입니다. EKS $${r.eks || "-"}, 네트워크 $${r.network || "-"}, 로그 $${r.logs || "-"}, push $${r.push || "-"}를 포함합니다.`;
          case "Unit Economics Agent":
            return `예상 비즈니스 가치는 $${r.expected_value_usd || "-"}이고 비용 비율은 ${r.cost_ratio || "-"}입니다. override는 ${r.override ? "검토가 필요합니다" : "권장하지 않습니다"}.`;
          case "Policy Guardrail Agent":
            return `정책상 ${(r.allowed || []).join(", ") || "필요 액션"}은 허용됩니다. 운영자 승인은 ${r.approval_required ? "필요합니다" : "필요하지 않습니다"}.`;
          case "Final Plan":
            return `권고사항을 최종 계획으로 정리했고 workflow 상태를 ${r.status || "waiting"}로 설정했습니다.`;
          case "Observer Agent":
            return `실행 중 관측을 준비했습니다. 첫 권고는 ${r.recommendation || "실제 RPS를 보고 용량을 조정"}입니다.`;
          case "Fallback Planner":
            return "실행이 안전하지 않으면 VIP 발송만 유지하고 일반 사용자는 hold하며 static report fallback을 제공합니다.";
          case "Postmortem Learning Agent":
            return `이벤트 종료 후 예측과 실제 결과를 비교합니다. 프로필 업데이트 상태는 ${r.profile_update || "pending"}입니다.`;
          case "Dry-run Execution":
            return "승인을 확인했습니다. scale-out, pre-warm, push schedule 등록을 dry-run으로 검증했습니다.";
          default:
            return JSON.stringify(r);
        }
      }

      function renderConversation(data) {
        const el = document.getElementById("agent-chat");
        document.getElementById("conversation-status").textContent = data.status || "running";
        const messages = data.conversation && data.conversation.length
          ? data.conversation.map(item => `
            <div class="bubble agent">
              <div class="speaker"><span>${escapeHtml(item.sender)}</span><span class="badge">to ${escapeHtml(item.receiver)}</span></div>
              <p>${escapeHtml(item.message)}</p>
            </div>
          `).join("")
          : (data.timeline || []).map(item => `
            <div class="bubble agent">
              <div class="speaker"><span>${escapeHtml(item.agent)}</span><span class="badge">${escapeHtml(item.status)}</span></div>
              <p>${escapeHtml(narrate(item))}</p>
            </div>
          `).join("");
        el.innerHTML = eventIntroBubble("요청") + messages;
        el.scrollTop = el.scrollHeight;
      }
      */

      function selectedEvent() {
        const selectedId = document.getElementById("event-select").value;
        return calendarItems.find(item => item.event_id === selectedId) || calendarItems[0];
      }

      function eventIntroBubble(label = "request") {
        const event = selectedEvent();
        if (!event) return "";
        const users = Number(event.target_users || 0).toLocaleString();
        return `
          <div class="bubble operator">
            <div class="speaker"><span>Operator</span><span class="badge">event</span></div>
            <p>${escapeHtml(event.scheduled_at)} ${escapeHtml(event.title)}: ${escapeHtml(label)} for ${users} target users.</p>
          </div>
        `;
      }

      function renderEmptyConversation() {
        document.getElementById("conversation-status").textContent = "ready";
        document.getElementById("agent-chat").innerHTML = `
          <div class="bubble agent">
            <div class="speaker"><span>FinOps MAS</span><span class="badge">ready</span></div>
            <p>Run the FinOps plan to execute the Temporal workflow and collect each agent result.</p>
          </div>
        `;
        updateChatAvailability();
      }

      function renderCallingConversation() {
        document.getElementById("conversation-status").textContent = "calling_agents";
        conversationHistory = [];
        document.getElementById("agent-chat").innerHTML = eventIntroBubble("FinOps plan") + `
          <div class="bubble agent">
            <div class="speaker"><span>Orchestrator</span><span class="badge">calling</span></div>
            <p>The Temporal workflow is dispatching work to the FinOps agent task queues.</p>
          </div>
        `;
        updateChatAvailability("running");
      }

      function narrate(item) {
        const r = item.result || {};
        const summaries = {
          "Business Control Agent": `Event grade ${r.grade || "unknown"}; approval ${r.approval_required ? "required" : "not required"}.`,
          "Demand Shaping Agent": `Send window ${r.send_window_minutes || "-"} minutes; estimated peak reduction ${r.peak_reduction_percent || "-"}%.`,
          "Traffic Forecast Agent": `Peak changes from ${r.peak_rps_before || "-"} to ${r.peak_rps_after || "-"} RPS; ${r.required_app_pods || "-"} pods required.`,
          "Bottleneck Capacity Agent": `Capacity status ${r.status || "unknown"}; DB CPU ${r.db_cpu || "-"}; cache hit ratio ${r.cache_hit_ratio || "-"}.`,
          "Infra Execution Planner": `Scale out at ${r.scale_out_at || "-"}; prewarm at ${r.prewarm_at || "-"}.`,
          "Cost Agent": `Estimated incremental cost $${r.total || "-"}.`,
          "Unit Economics Agent": `Cost-to-value ratio ${r.cost_ratio || "-"}.`,
          "Policy Guardrail Agent": `Approval ${r.approval_required ? "required" : "not required"}.`,
          "Observer Agent": r.recommendation || "Monitoring thresholds prepared.",
          "Fallback Planner": "Fallback actions prepared for approval or infrastructure failure.",
          "Postmortem Learning Agent": `Profile update ${r.profile_update || "pending"}.`,
          "Dry-run Execution": "The approved operation plan was validated in dry-run mode."
        };
        return summaries[item.agent] || JSON.stringify(r);
      }

      function renderConversation(data) {
        const el = document.getElementById("agent-chat");
        document.getElementById("conversation-status").textContent = data.status || "running";
        const messages = data.conversation && data.conversation.length
          ? data.conversation.map(item => `
            <div class="bubble agent">
              <div class="speaker"><span>${escapeHtml(item.sender)}</span><span class="badge">to ${escapeHtml(item.receiver)}</span></div>
              <p>${escapeHtml(item.message)}</p>
            </div>
          `).join("")
          : (data.timeline || []).map(item => `
            <div class="bubble agent">
              <div class="speaker"><span>${escapeHtml(item.agent)}</span><span class="badge">${escapeHtml(item.status)}</span></div>
              <p>${escapeHtml(narrate(item))}</p>
            </div>
          `).join("");
        el.innerHTML = eventIntroBubble("FinOps plan") + messages;
        el.scrollTop = el.scrollHeight;
        updateChatAvailability(data.status);
      }

      function renderAgentCards(agents) {
        agentDetails = Object.fromEntries(agents.map(item => [item.agent_key, item]));
        const el = document.getElementById("agent-cards");
        el.innerHTML = agents.length ? agents.map(item => `
          <div class="agent-card" onclick="openAgentModal('${escapeHtml(item.agent_key)}')">
            <div class="speaker">
              <span>${escapeHtml(item.agent_name)}</span>
              <span class="badge status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
            </div>
            <p>confidence: ${item.confidence === null ? "-" : Number(item.confidence).toFixed(2)}</p>
            <span class="badge">${escapeHtml(item.reasoning_source || "pending")}</span>
            <details><summary>Evidence</summary><ul>${(item.evidence || []).map(value => `<li>${escapeHtml(value)}</li>`).join("") || "<li>-</li>"}</ul></details>
            <details><summary>Warnings</summary><ul class="warning">${(item.warnings || []).map(value => `<li>${escapeHtml(value)}</li>`).join("") || "<li>-</li>"}</ul></details>
            <div class="muted">${escapeHtml(item.started_at || "-")} → ${escapeHtml(item.completed_at || "-")}</div>
          </div>`).join("") : '<div class="muted">Waiting for agent activities.</div>';
      }

      function openAgentModal(agentKey) {
        const item = agentDetails[agentKey];
        if (!item) return;
        document.getElementById("modal-agent-name").textContent = item.agent_name;
        document.getElementById("modal-agent-body").innerHTML = `
          <details open><summary>Input Context</summary><pre>${escapeHtml(JSON.stringify(item.input_context || {}, null, 2))}</pre></details>
          <details open><summary>Output Result</summary><pre>${escapeHtml(JSON.stringify(item.result || {}, null, 2))}</pre></details>
          <details><summary>Data Requests</summary><pre>${escapeHtml(JSON.stringify(item.data_requests || [], null, 2))}</pre></details>
          <details><summary>Evidence</summary><pre>${escapeHtml(JSON.stringify(item.evidence || [], null, 2))}</pre></details>
          <details><summary>Warnings</summary><pre>${escapeHtml(JSON.stringify(item.warnings || [], null, 2))}</pre></details>`;
        document.getElementById("agent-modal").hidden = false;
      }

      function closeAgentModal() {
        document.getElementById("agent-modal").hidden = true;
      }

      function renderBrokerLog(entries) {
        const el = document.getElementById("broker-log");
        el.innerHTML = entries.length ? entries.map(item => {
          const requester = agentDetails[item.requester_agent]?.agent_name || item.requester_agent || "Agent";
          const target = agentDetails[item.target_agent]?.agent_name || item.target_agent || "Agent";
          const cache = item.cache_hit ? "✓ cache hit" : "✗ new execution";
          const fields = (item.result_fields || []).join(", ") || "none";
          return `<div class="broker-flow"><strong>${escapeHtml(requester)}</strong> → [${escapeHtml(item.operation)}] → <strong>${escapeHtml(target)}</strong><br>${cache} · ${escapeHtml(item.broker_status)} · 반환: ${escapeHtml(fields)}<br><span class="muted">${escapeHtml(item.reason || "")}</span></div>`;
        }).join("") : '<span class="muted">No broker calls.</span>';
      }

      async function retryPlan() {
        if (!currentWorkflow) return;
        try {
          stopWorkflowPolling();
          stopExecutionPolling();
          currentExecution = null;
          document.getElementById("execution-section").hidden = true;
          const result = await api(`/api/workflows/${currentWorkflow}/retry`, {method: "POST"});
          previousWorkflow = currentWorkflow;
          previousPlanSnapshot = currentPlanSnapshot;
          currentWorkflow = result.new_workflow_id;
          renderCallingConversation();
          await loadWorkflow(currentWorkflow);
          startWorkflowPolling(currentWorkflow);
        } catch (error) { showError(error); }
      }

      function stopWorkflowPolling() {
        if (workflowPoller) {
          clearInterval(workflowPoller);
          workflowPoller = null;
        }
      }

      function startWorkflowPolling(workflowId) {
        stopWorkflowPolling();
        workflowPoller = setInterval(async () => {
          try {
            const done = await loadWorkflow(workflowId);
            if (done) {
              stopWorkflowPolling();
              document.getElementById("toast").textContent = "";
            }
          } catch (error) {
            showError(error);
          }
        }, 1000);
      }

      function executionStepLabel(stepType) {
        const labels = {
          scale_out: "Scale Out",
          cache_prewarm: "Cache Prewarm",
          push_schedule: "Push Schedule",
          verify_ready: "Verify Ready",
          go_no_go: "Go / No-Go",
          scale_down_watch: "Scale-down Watch"
        };
        return labels[stepType] || stepType;
      }

      function renderExecution(data) {
        const section = document.getElementById("execution-section");
        const status = document.getElementById("execution-status");
        const stepsEl = document.getElementById("execution-steps");
        section.hidden = false;
        status.textContent = `${data.status || "pending"} / ${data.mode || "dry_run"}`;
        status.className = `badge status-${escapeHtml(data.status || "pending")}`;

        const plannedSteps = data.execution_plan?.steps || [];
        const loggedById = Object.fromEntries((data.steps || []).map(item => [item.step_id, item]));
        const mergedSteps = plannedSteps.length
          ? plannedSteps.map(step => ({...step, ...(loggedById[step.step_id] || {})}))
          : (data.steps || []);

        stepsEl.innerHTML = mergedSteps.length ? mergedSteps.map(step => {
          const result = step.result || {};
          const statusValue = step.status || "pending";
          return `
            <div class="agent-card">
              <div class="speaker">
                <span>${escapeHtml(executionStepLabel(step.step_type))}</span>
                <span class="badge status-${escapeHtml(statusValue)}">${escapeHtml(statusValue)}</span>
              </div>
              <p class="muted">${escapeHtml(step.scheduled_at || "-")}</p>
              <details open><summary>Parameters</summary><pre class="report-json">${escapeHtml(JSON.stringify(step.parameters || {}, null, 2))}</pre></details>
              <details><summary>Dry-run Result</summary><pre class="report-json">${escapeHtml(JSON.stringify(result, null, 2))}</pre></details>
              <div class="muted">${escapeHtml(step.started_at || "-")} → ${escapeHtml(step.completed_at || "-")}</div>
            </div>
          `;
        }).join("") : '<div class="muted">Execution dry-run is waiting for steps.</div>';
      }

      async function loadExecution(executionWorkflowId) {
        const data = await api(`/api/executions/${executionWorkflowId}`);
        renderExecution(data);
        return ["completed", "failed"].includes(data.status || "");
      }

      function stopExecutionPolling() {
        if (executionPoller) {
          clearInterval(executionPoller);
          executionPoller = null;
        }
      }

      function startExecutionPolling(executionWorkflowId) {
        stopExecutionPolling();
        executionPoller = setInterval(async () => {
          try {
            const done = await loadExecution(executionWorkflowId);
            if (done) stopExecutionPolling();
          } catch (error) {
            showError(error);
          }
        }, 2000);
      }

      async function loadWorkflow(workflowId) {
        const [data, agents, brokerLog] = await Promise.all([
          api(`/api/workflows/${workflowId}`),
          api(`/api/workflows/${workflowId}/agents`),
          api(`/api/workflows/${workflowId}/broker-log`)
        ]);
        renderPlan(data);
        renderConversation(data);
        renderAgentCards(agents);
        renderBrokerLog(brokerLog);
        return !["running", "starting"].includes(data.status || "running");
      }

      async function runPlan() {
        try {
          stopWorkflowPolling();
          stopExecutionPolling();
          document.getElementById("toast").textContent = "Temporal workflow 시작 중...";
          previousWorkflow = null;
          previousPlanSnapshot = null;
          currentExecution = null;
          pendingReplan = null;
          document.getElementById("execution-section").hidden = true;
          renderCallingConversation();
          const eventId = document.getElementById("event-select").value || "fomc-briefing";
          const result = await api(`/api/workflows/run?event_id=${encodeURIComponent(eventId)}`, {method: "POST"});
          currentWorkflow = result.workflow_id;
          await loadWorkflow(currentWorkflow);
          startWorkflowPolling(currentWorkflow);
        } catch (error) {
          showError(error);
        }
      }

      loadDashboard();
    </script>
  </body>
</html>
"""
