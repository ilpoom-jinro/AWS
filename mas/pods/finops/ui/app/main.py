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
        grid-template-columns: 360px minmax(0, 1fr);
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
        min-height: 560px;
        max-height: calc(100vh - 376px);
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
      #toast { color: var(--warn); font-size: 13px; }
      @media (max-width: 1020px) {
        .summary { grid-template-columns: 1fr; }
        .content-grid { grid-template-columns: 1fr; }
        .metric { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .chat-room { max-height: none; }
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
          <p class="muted">선택한 비즈니스 이벤트에 대해 agent들에게 재계획을 요청합니다.</p>
          <textarea id="chat-message">일반 사용자를 20분 동안 분산 발송해줘</textarea>
            <div class="row" style="margin-top: 10px;">
              <button class="secondary" onclick="sendChat()">Send Change Request</button>
              <div id="toast"></div>
            </div>
          </section>
        </div>
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
