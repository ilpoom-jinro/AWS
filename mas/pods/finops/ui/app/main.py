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

app = FastAPI(title="FinOps UI Agent", version="0.3.0")


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
        max-width: 1440px;
        margin: 0 auto;
        padding: 18px;
        display: grid;
        grid-template-columns: 340px minmax(460px, 1fr) 340px;
        gap: 16px;
        align-items: start;
      }
      section, .card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px;
      }
      .stack { display: grid; gap: 12px; }
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
        gap: 6px;
        margin-top: 12px;
      }
      .day-name { color: var(--muted); font-size: 11px; font-weight: 700; text-align: center; }
      .day {
        min-height: 72px;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 7px;
        background: #fff;
      }
      .day.outside { background: #f1f5f9; color: #94a3b8; }
      .day.today { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
      .date-number { font-size: 12px; font-weight: 700; }
      .event-pill {
        margin-top: 6px;
        border-radius: 6px;
        background: var(--accent-soft);
        color: #1e3a8a;
        padding: 5px;
        font-size: 11px;
        line-height: 1.25;
        font-weight: 700;
      }
      .chat-room {
        min-height: 520px;
        max-height: calc(100vh - 284px);
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
      .metric { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
      .metric .card { padding: 12px; }
      .value { font-size: 23px; font-weight: 700; margin-top: 6px; }
      .timeline { display: grid; gap: 8px; max-height: calc(100vh - 310px); overflow: auto; padding-right: 4px; }
      .phase {
        display: grid;
        grid-template-columns: 42px 1fr auto;
        gap: 10px;
        align-items: start;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 10px;
      }
      pre {
        margin: 8px 0 0;
        white-space: pre-wrap;
        word-break: break-word;
        color: var(--muted);
        font-size: 12px;
      }
      #toast { color: var(--warn); font-size: 13px; }
      @media (max-width: 1020px) {
        main { grid-template-columns: 1fr; }
        .chat-room, .timeline { max-height: none; }
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
            <span id="calendar-month" class="badge">Month</span>
          </div>
          <div id="calendar" class="calendar-grid"></div>
        </section>
      </div>

      <div class="stack">
        <section>
          <div class="row">
            <h2>Agent Conversation</h2>
            <span id="conversation-status" class="badge">idle</span>
          </div>
          <div id="agent-chat" class="chat-room" style="margin-top: 12px;"></div>
        </section>
        <section>
          <h2>ChatOps</h2>
          <p class="muted">Ask the agents to re-plan the selected business event.</p>
          <textarea id="chat-message">Spread general users over 20 minutes</textarea>
          <div class="row" style="margin-top: 10px;">
            <button class="secondary" onclick="sendChat()">Send Change Request</button>
            <div id="toast"></div>
          </div>
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
      let calendarItems = [];

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
          renderCalendar(calendarItems);
          if (data.active_workflow) {
            currentWorkflow = data.active_workflow.workflow_id;
            await loadWorkflow(currentWorkflow);
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
        const start = new Date(first);
        start.setDate(first.getDate() - first.getDay());
        const names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        const headers = names.map(name => `<div class="day-name">${name}</div>`).join("");
        const days = [];
        for (let i = 0; i < 42; i++) {
          const date = new Date(start);
          date.setDate(start.getDate() + i);
          const isToday = date.toDateString() === now.toDateString();
          const outside = date.getMonth() !== month;
          const events = isToday ? items.map(item => `
            <div class="event-pill">${item.title}<br>${item.scheduled_at} / Grade ${item.grade}</div>
          `).join("") : "";
          days.push(`
            <div class="day ${outside ? "outside" : ""} ${isToday ? "today" : ""}">
              <div class="date-number">${date.getDate()}</div>${events}
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
        renderTimeline(data.timeline || []);
        renderConversation(data);
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
            <div><strong>${item.agent}</strong><pre>${JSON.stringify(item.result, null, 2)}</pre></div>
            <span class="badge">${item.status}</span>
          </div>
        `).join("");
      }

      function renderEmptyConversation() {
        document.getElementById("conversation-status").textContent = "waiting";
        document.getElementById("agent-chat").innerHTML = `
          <div class="bubble agent">
            <div class="speaker"><span>Business Control Agent</span><span class="badge">ready</span></div>
            <p>I found the business calendar. Run a FinOps plan and I will coordinate the agents for today's event.</p>
          </div>
        `;
      }

      function narrate(item) {
        const r = item.result || {};
        switch (item.agent) {
          case "Business Control Agent":
            return `I found ${r.event_id || "the scheduled event"} and classified it as grade ${r.grade || "unknown"}. Approval is ${r.approval_required ? "required" : "not required"} before execution.`;
          case "Demand Shaping Agent":
            return `I will send VIP users ${r.vip || "first"} and move general users to ${r.general_users || "a distributed window"}. That lowers peak traffic by about ${r.peak_reduction || "a meaningful amount"}.`;
          case "Traffic Forecast Agent":
            return `Before shaping I expect ${r.peak_rps_before || "-"} rps. After shaping I expect ${r.peak_rps_after || "-"} rps, so the app tier should prepare ${r.required_app_pods || "-"} pods.`;
          case "Bottleneck Capacity Agent":
            return `I checked the bottlenecks. DB CPU is around ${r.db_cpu || "-"}, cache hit ratio is ${r.cache_hit_ratio || "-"}, and the status is ${r.status || "unknown"}.`;
          case "Infra Execution Planner":
            return `I recommend scale-out at ${r.scale_out_at || "-"}, pre-warm at ${r.prewarm_at || "-"}, and scale-down based on ${r.scale_down || "observed traffic"}.`;
          case "Cost Agent":
            return `The estimated event cost is $${r.total || "-"}, including EKS $${r.eks || "-"}, network $${r.network || "-"}, logs $${r.logs || "-"}, and push $${r.push || "-"}.`;
          case "Unit Economics Agent":
            return `Expected business value is about $${r.expected_value_usd || "-"} and the cost ratio is ${r.cost_ratio || "-"}. I do ${r.override ? "" : "not "}recommend an override.`;
          case "Policy Guardrail Agent":
            return `Policy allows ${(r.allowed || []).join(", ") || "the proposed actions"}. Operator approval is ${r.approval_required ? "required" : "not required"}.`;
          case "Final Plan":
            return `I packaged the recommendations into a final plan and set the workflow status to ${r.status || "waiting"}.`;
          case "Observer Agent":
            return `I am ready for runtime observation. My first recommendation is: ${r.recommendation || "watch actual traffic and adjust capacity"}.`;
          case "Fallback Planner":
            return "If execution becomes unsafe, I will keep VIP delivery, hold general users, and provide a static report fallback.";
          case "Postmortem Learning Agent":
            return `After the event, I will compare forecast and actual results. Profile update is ${r.profile_update || "pending"}.`;
          case "Dry-run Execution":
            return "Approval received. I completed the dry-run checks for scale-out, pre-warm, and push schedule registration.";
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
            <p>Please prepare a FinOps plan for ${event.title} at ${event.scheduled_at}. Target users: ${event.target_users.toLocaleString()}.</p>
          </div>
        ` : "";
        el.innerHTML = intro + (data.timeline || []).map(item => `
          <div class="bubble agent">
            <div class="speaker"><span>${item.agent}</span><span class="badge">${item.status}</span></div>
            <p>${narrate(item)}</p>
          </div>
        `).join("");
        el.scrollTop = el.scrollHeight;
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
          const el = document.getElementById("agent-chat");
          el.innerHTML += `
            <div class="bubble operator">
              <div class="speaker"><span>Operator</span><span class="badge">change</span></div>
              <p>${message}</p>
            </div>
            <div class="bubble agent">
              <div class="speaker"><span>${data.agent}</span><span class="badge">reply</span></div>
              <p>${data.answer}</p>
            </div>
          `;
          el.scrollTop = el.scrollHeight;
        } catch (error) {
          showError(error);
        }
      }

      loadDashboard();
    </script>
  </body>
</html>
"""
