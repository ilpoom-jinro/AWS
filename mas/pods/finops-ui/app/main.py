from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


app = FastAPI(title="FinOps MAS UI", version="0.1.0")


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str


class ChatResponse(BaseModel):
    message: ChatMessage
    plan_preview: dict[str, object]


class BusinessCalendarEvent(BaseModel):
    id: str
    title: str
    starts_at: str
    expected_users: str
    push_channel: str
    warmup_minutes_before: int
    grace_minutes_after: int
    warm_pool_nodes: int
    status: Literal["scheduled", "warming", "awaiting_signal", "released", "cancelled"]
    guardrail: str


MESSAGES: list[ChatMessage] = [
    ChatMessage(
        id=str(uuid4()),
        role="assistant",
        content=(
            "FinOps UI is ready. Ask about traffic spikes, cost impact, "
            "capacity, RDS pressure, or an approval plan."
        ),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
]

CALENDAR_EVENTS: list[BusinessCalendarEvent] = []


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_calendar_events() -> list[BusinessCalendarEvent]:
    if CALENDAR_EVENTS:
        return CALENDAR_EVENTS

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    CALENDAR_EVENTS.extend(
        [
            BusinessCalendarEvent(
                id="push-fomc-briefing",
                title="FOMC report push notification",
                starts_at=(now + timedelta(hours=3)).isoformat(),
                expected_users="350k users",
                push_channel="mobile-push",
                warmup_minutes_before=30,
                grace_minutes_after=45,
                warm_pool_nodes=20,
                status="scheduled",
                guardrail="Release warm pool if DB signal is not received by T+45m.",
            ),
            BusinessCalendarEvent(
                id="push-market-open",
                title="Market open portfolio digest",
                starts_at=(now + timedelta(days=1, hours=1)).isoformat(),
                expected_users="180k users",
                push_channel="mobile-push",
                warmup_minutes_before=20,
                grace_minutes_after=30,
                warm_pool_nodes=10,
                status="scheduled",
                guardrail="Cancel workflow when the business calendar event is cancelled.",
            ),
            BusinessCalendarEvent(
                id="push-earnings-summary",
                title="Earnings summary campaign",
                starts_at=(now - timedelta(minutes=15)).isoformat(),
                expected_users="90k users",
                push_channel="email-and-push",
                warmup_minutes_before=15,
                grace_minutes_after=30,
                warm_pool_nodes=6,
                status="awaiting_signal",
                guardrail="Auto-scale down at the cleanup deadline unless a DB signal arrives.",
            ),
        ]
    )
    return CALENDAR_EVENTS


def event_schedule_view(event: BusinessCalendarEvent) -> dict[str, object]:
    starts_at = datetime.fromisoformat(event.starts_at)
    warmup_at = starts_at - timedelta(minutes=event.warmup_minutes_before)
    cleanup_at = starts_at + timedelta(minutes=event.grace_minutes_after)
    return {
        **event.model_dump(),
        "warmup_at": warmup_at.isoformat(),
        "cleanup_at": cleanup_at.isoformat(),
        "workflow_id": f"calendar-warmup-{event.id}",
        "timeout_policy": {
            "await_db_signal_until": cleanup_at.isoformat(),
            "on_timeout": [
                "scale warm pool back to baseline",
                "mark workflow released",
                "emit cost-control audit event",
            ],
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard() -> dict[str, object]:
    return {
        "service": "finops-mas",
        "cluster": "financial-ops-eks",
        "mode": "dry-run",
        "signals": [
            {"name": "Expected traffic", "value": "350k users", "status": "watch"},
            {"name": "Monthly budget used", "value": "83%", "status": "ok"},
            {"name": "RDS read IOPS", "value": "78%", "status": "watch"},
            {"name": "Warm pool", "value": "20 nodes ready", "status": "ok"},
            {"name": "Next push warmup", "value": "T-30m", "status": "watch"},
        ],
        "recommendation": {
            "summary": "Use business-calendar warmup, then release capacity automatically if the DB signal never arrives.",
            "actions": [
                "Poll the business calendar every hour",
                "Create one workflow per push notification event",
                "Start warm pool capacity at T-30m",
                "Wait for the DB signal before pod scale-out",
                "Garbage-collect unused capacity at T+45m",
                "Add on-demand nodes if queue pressure rises",
                "Prepare one read replica",
                "Throttle push notification rate by 30%",
                "Set CDN cache TTL to 15 minutes",
            ],
            "estimated_extra_cost_usd": 420,
            "estimated_failure_risk": "12% -> 3%",
        },
    }


@app.get("/api/calendar")
def calendar() -> dict[str, object]:
    events = [event_schedule_view(event) for event in seed_calendar_events()]
    return {
        "polling_interval": "1 hour",
        "source": "business-calendar-api",
        "events": events,
    }


@app.get("/api/chat", response_model=list[ChatMessage])
def list_chat() -> list[ChatMessage]:
    return MESSAGES


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    prompt = request.prompt.strip()
    user_message = ChatMessage(
        id=str(uuid4()),
        role="user",
        content=prompt,
        created_at=now_utc(),
    )

    response_text = build_mock_finops_response(prompt)
    assistant_message = ChatMessage(
        id=str(uuid4()),
        role="assistant",
        content=response_text,
        created_at=now_utc(),
    )

    MESSAGES.extend([user_message, assistant_message])
    return {
        "message": assistant_message,
        "plan_preview": {
            "approval_required": True,
            "execution_mode": "dry-run",
            "next_agent": "finops-orchestrator",
        },
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


def build_mock_finops_response(prompt: str) -> str:
    lowered = prompt.lower()

    if any(word in lowered for word in ["cost", "budget", "bill", "spend"]):
        focus = "Cost Agent"
        finding = "Budget headroom exists, but every scale action should show unit economics."
    elif any(word in lowered for word in ["rds", "db", "database", "iops"]):
        focus = "DB Agent"
        finding = "Read pressure is elevated. Prepare one read replica before peak traffic."
    elif any(word in lowered for word in ["calendar", "schedule", "push", "timeout", "gc", "garbage"]):
        focus = "Business Calendar Agent"
        finding = (
            "Create a durable workflow per calendar event, warm nodes before the push, "
            "then use a signal timeout to release unused capacity."
        )
    elif any(word in lowered for word in ["traffic", "user", "spike", "fomc"]):
        focus = "Traffic Agent"
        finding = "Traffic concentration is likely. Use staged scale-out and push throttling."
    elif any(word in lowered for word in ["node", "eks", "infra", "capacity"]):
        focus = "Infra Agent"
        finding = "Warm pool capacity is available. Prefer it before adding new spot capacity."
    else:
        focus = "Orchestrator"
        finding = "I would collect business, traffic, infra, DB, cost, and unit economics opinions."

    return (
        f"{focus} draft opinion: {finding}\n\n"
        "Recommended dry-run plan:\n"
        "1. Validate current demand forecast.\n"
        "2. Estimate extra infrastructure cost.\n"
        "3. Compare failure-risk reduction against business value.\n"
        "4. Submit the plan for human approval before execution."
    )


HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>FinOps MAS</title>
    <style>
      :root {
        color-scheme: light;
        --bg: #f6f7f9;
        --panel: #ffffff;
        --ink: #18202a;
        --muted: #637083;
        --line: #d9dee7;
        --accent: #176b5b;
        --accent-strong: #0f4f43;
        --warn: #9a5b00;
        --ok: #177245;
      }

      * {
        box-sizing: border-box;
      }

      body {
        margin: 0;
        min-height: 100vh;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: var(--ink);
        background: var(--bg);
      }

      .shell {
        display: grid;
        grid-template-columns: minmax(0, 1.1fr) minmax(360px, 0.9fr);
        gap: 20px;
        width: min(1280px, calc(100vw - 32px));
        margin: 0 auto;
        padding: 24px 0;
      }

      header {
        grid-column: 1 / -1;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
      }

      h1 {
        margin: 0;
        font-size: 28px;
        letter-spacing: 0;
      }

      .subtle {
        color: var(--muted);
        margin: 6px 0 0;
      }

      .badge {
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 8px 12px;
        background: var(--panel);
        color: var(--accent-strong);
        font-weight: 700;
      }

      .panel {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
      }

      .dashboard {
        padding: 18px;
      }

      .section-title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 14px;
      }

      h2 {
        margin: 0;
        font-size: 18px;
      }

      .cards {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
      }

      .card {
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px;
        min-height: 96px;
      }

      .metric-name {
        color: var(--muted);
        font-size: 13px;
      }

      .metric-value {
        margin-top: 10px;
        font-size: 24px;
        font-weight: 800;
      }

      .status {
        margin-top: 10px;
        font-size: 13px;
        font-weight: 700;
      }

      .status.ok {
        color: var(--ok);
      }

      .status.watch {
        color: var(--warn);
      }

      .recommendation {
        margin-top: 16px;
        padding: 16px;
        border: 1px solid var(--line);
        border-radius: 8px;
      }

      .recommendation ul {
        margin: 12px 0 0;
        padding-left: 20px;
      }

      .recommendation li {
        margin: 8px 0;
      }

      .calendar {
        margin-top: 16px;
      }

      .event-list {
        display: grid;
        gap: 12px;
      }

      .event {
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px;
      }

      .event-head {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: flex-start;
      }

      .event-title {
        font-weight: 800;
      }

      .event-meta {
        color: var(--muted);
        font-size: 13px;
        margin-top: 6px;
      }

      .workflow {
        margin-top: 12px;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
      }

      .workflow span {
        background: #f6f7f9;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 8px;
        font-size: 13px;
      }

      .guardrail {
        margin-top: 10px;
        color: var(--accent-strong);
        font-weight: 700;
        font-size: 13px;
      }

      .impact {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 14px;
      }

      .impact span {
        border-radius: 8px;
        background: #eef4f2;
        color: var(--accent-strong);
        padding: 8px 10px;
        font-weight: 700;
      }

      .chat {
        display: grid;
        grid-template-rows: auto minmax(360px, 1fr) auto;
        min-height: 680px;
      }

      .chat-header {
        padding: 16px 18px;
        border-bottom: 1px solid var(--line);
      }

      .messages {
        padding: 16px;
        overflow: auto;
      }

      .message {
        max-width: 92%;
        margin-bottom: 12px;
        padding: 12px 14px;
        border-radius: 8px;
        white-space: pre-wrap;
        line-height: 1.45;
      }

      .message.assistant {
        background: #eef4f2;
        border: 1px solid #d0e2dc;
      }

      .message.user {
        margin-left: auto;
        color: #ffffff;
        background: var(--accent);
      }

      form {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 10px;
        padding: 14px;
        border-top: 1px solid var(--line);
      }

      textarea {
        width: 100%;
        min-height: 48px;
        max-height: 140px;
        resize: vertical;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 12px;
        font: inherit;
      }

      button {
        border: 0;
        border-radius: 8px;
        background: var(--accent);
        color: #ffffff;
        padding: 0 18px;
        font-weight: 800;
        cursor: pointer;
      }

      button:hover {
        background: var(--accent-strong);
      }

      button:disabled {
        cursor: wait;
        opacity: 0.7;
      }

      @media (max-width: 860px) {
        .shell {
          grid-template-columns: 1fr;
          width: min(100vw - 20px, 720px);
          padding: 16px 0;
        }

        header {
          align-items: flex-start;
          flex-direction: column;
        }

        .cards {
          grid-template-columns: 1fr;
        }

        .chat {
          min-height: 560px;
        }
      }
    </style>
  </head>
  <body>
    <main class="shell">
      <header>
        <div>
          <h1>FinOps MAS</h1>
          <p class="subtle">State-based FinOps dashboard for the ops VPC.</p>
        </div>
        <div class="badge" id="mode">dry-run</div>
      </header>

      <section class="panel dashboard">
        <div class="section-title">
          <h2>Operational Signals</h2>
          <span class="subtle" id="cluster">financial-ops-eks</span>
        </div>
        <div class="cards" id="signals"></div>

        <div class="recommendation">
          <div class="section-title">
            <h2>Plan Preview</h2>
            <span class="subtle">approval required</span>
          </div>
          <p id="summary"></p>
          <ul id="actions"></ul>
          <div class="impact">
            <span id="cost"></span>
            <span id="risk"></span>
          </div>
        </div>

        <div class="calendar">
          <div class="section-title">
            <h2>Business Calendar</h2>
            <span class="subtle" id="polling">polling</span>
          </div>
          <div class="event-list" id="calendar-events"></div>
        </div>
      </section>

      <section class="panel chat">
        <div class="chat-header">
          <h2>FinOps Chat</h2>
          <p class="subtle">Ask for cost, traffic, capacity, DB, or approval-plan analysis.</p>
        </div>
        <div class="messages" id="messages"></div>
        <form id="chat-form">
          <textarea id="prompt" placeholder="Example: FOMC report traffic spike is expected. What should we prepare?"></textarea>
          <button id="send" type="submit">Send</button>
        </form>
      </section>
    </main>

    <script>
      const signalsEl = document.querySelector("#signals");
      const calendarEventsEl = document.querySelector("#calendar-events");
      const messagesEl = document.querySelector("#messages");
      const form = document.querySelector("#chat-form");
      const promptEl = document.querySelector("#prompt");
      const sendEl = document.querySelector("#send");

      function formatDate(value) {
        return new Intl.DateTimeFormat(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }).format(new Date(value));
      }

      function renderMessage(message) {
        const node = document.createElement("div");
        node.className = `message ${message.role}`;
        node.textContent = message.content;
        messagesEl.appendChild(node);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }

      async function loadDashboard() {
        const response = await fetch("/api/dashboard");
        const data = await response.json();
        document.querySelector("#mode").textContent = data.mode;
        document.querySelector("#cluster").textContent = data.cluster;
        signalsEl.innerHTML = "";
        data.signals.forEach((signal) => {
          const card = document.createElement("div");
          card.className = "card";
          card.innerHTML = `
            <div class="metric-name"></div>
            <div class="metric-value"></div>
            <div class="status"></div>
          `;
          card.querySelector(".metric-name").textContent = signal.name;
          card.querySelector(".metric-value").textContent = signal.value;
          const status = card.querySelector(".status");
          status.textContent = signal.status;
          status.classList.add(signal.status);
          signalsEl.appendChild(card);
        });

        document.querySelector("#summary").textContent = data.recommendation.summary;
        document.querySelector("#cost").textContent = `Extra cost: $${data.recommendation.estimated_extra_cost_usd}`;
        document.querySelector("#risk").textContent = `Failure risk: ${data.recommendation.estimated_failure_risk}`;
        const actions = document.querySelector("#actions");
        actions.innerHTML = "";
        data.recommendation.actions.forEach((action) => {
          const item = document.createElement("li");
          item.textContent = action;
          actions.appendChild(item);
        });
      }

      async function loadCalendar() {
        const response = await fetch("/api/calendar");
        const data = await response.json();
        document.querySelector("#polling").textContent = `${data.source} / ${data.polling_interval}`;
        calendarEventsEl.innerHTML = "";

        data.events.forEach((event) => {
          const node = document.createElement("div");
          node.className = "event";
          node.innerHTML = `
            <div class="event-head">
              <div>
                <div class="event-title"></div>
                <div class="event-meta"></div>
              </div>
              <span class="badge"></span>
            </div>
            <div class="workflow">
              <span class="warmup"></span>
              <span class="signal"></span>
              <span class="cleanup"></span>
            </div>
            <div class="guardrail"></div>
          `;

          node.querySelector(".event-title").textContent = event.title;
          node.querySelector(".event-meta").textContent =
            `${event.expected_users} / ${event.push_channel} / ${event.warm_pool_nodes} warm nodes`;
          node.querySelector(".badge").textContent = event.status.replace("_", " ");
          node.querySelector(".warmup").textContent = `Warmup: ${formatDate(event.warmup_at)}`;
          node.querySelector(".signal").textContent = `Signal: DB event`;
          node.querySelector(".cleanup").textContent = `GC: ${formatDate(event.cleanup_at)}`;
          node.querySelector(".guardrail").textContent = event.guardrail;
          calendarEventsEl.appendChild(node);
        });
      }

      async function loadMessages() {
        const response = await fetch("/api/chat");
        const messages = await response.json();
        messagesEl.innerHTML = "";
        messages.forEach(renderMessage);
      }

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const prompt = promptEl.value.trim();
        if (!prompt) return;

        renderMessage({
          role: "user",
          content: prompt,
        });
        promptEl.value = "";
        sendEl.disabled = true;

        try {
          const response = await fetch("/api/chat", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({prompt}),
          });
          const data = await response.json();
          renderMessage(data.message);
        } finally {
          sendEl.disabled = false;
          promptEl.focus();
        }
      });

      loadDashboard();
      loadCalendar();
      loadMessages();
    </script>
  </body>
</html>
"""
