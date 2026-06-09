from datetime import datetime, timezone
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


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        ],
        "recommendation": {
            "summary": "Prepare scale-out plan and require human approval.",
            "actions": [
                "Start warm pool capacity",
                "Add on-demand nodes if queue pressure rises",
                "Prepare one read replica",
                "Throttle push notification rate by 30%",
                "Set CDN cache TTL to 15 minutes",
            ],
            "estimated_extra_cost_usd": 420,
            "estimated_failure_risk": "12% -> 3%",
        },
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
      const messagesEl = document.querySelector("#messages");
      const form = document.querySelector("#chat-form");
      const promptEl = document.querySelector("#prompt");
      const sendEl = document.querySelector("#send");

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
      loadMessages();
    </script>
  </body>
</html>
"""
