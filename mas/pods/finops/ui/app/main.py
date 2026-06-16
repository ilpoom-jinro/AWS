from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


app = FastAPI(title="FinOps UI Agent", version="0.1.0")


class ChatRequest(BaseModel):
    prompt: str


class ChatResponse(BaseModel):
    answer: str
    suggested_actions: list[str]
    generated_at: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    return {
        "scenario": "finops",
        "agent": "ui",
        "namespace": "finops-mas",
        "signals": [
            {"name": "Monthly cost trend", "status": "watch", "value": "+8.4%"},
            {"name": "Idle compute", "status": "actionable", "value": "3 node groups"},
            {"name": "RDS utilization", "status": "review", "value": "22% avg CPU"},
        ],
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    prompt = request.prompt.strip()
    lowered = prompt.lower()

    if any(token in lowered for token in ["cost", "비용", "절감", "saving"]):
        answer = "현재 비용 최적화 관점에서는 유휴 컴퓨트와 낮은 RDS 사용률을 먼저 확인하는 것이 좋습니다."
        actions = [
            "노드 그룹별 요청량/사용량 비교",
            "RDS 인스턴스 클래스와 평균 CPU 확인",
            "최근 7일 비용 증가 서비스 분해",
        ]
    elif any(token in lowered for token in ["pod", "eks", "kubernetes", "cluster"]):
        answer = "EKS 관점에서는 namespace별 리소스 요청량과 실제 사용량 차이를 우선 확인할 수 있습니다."
        actions = [
            "finops-mas namespace Pod 상태 확인",
            "requests/limits 미설정 workload 점검",
            "노드 풀별 bin packing 상태 확인",
        ]
    else:
        answer = "FinOps 분석을 위해 비용, EKS, RDS, 트래픽 중 어떤 영역을 볼지 알려주세요."
        actions = [
            "이번 달 비용 증가 원인 질문",
            "유휴 리소스 조회 질문",
            "특정 namespace 비용 분석 질문",
        ]

    return ChatResponse(
        answer=answer,
        suggested_actions=actions,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>FinOps UI Agent</title>
    <style>
      body {
        margin: 0;
        font-family: Arial, sans-serif;
        background: #f6f8fb;
        color: #1f2937;
      }
      main {
        max-width: 1040px;
        margin: 0 auto;
        padding: 32px 20px;
      }
      header {
        margin-bottom: 24px;
      }
      h1 {
        margin: 0 0 8px;
        font-size: 28px;
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        margin-bottom: 20px;
      }
      .card, .chat {
        background: #ffffff;
        border: 1px solid #d9e0ea;
        border-radius: 8px;
        padding: 16px;
      }
      .label {
        color: #64748b;
        font-size: 13px;
      }
      .value {
        margin-top: 8px;
        font-size: 22px;
        font-weight: 700;
      }
      textarea {
        width: 100%;
        min-height: 96px;
        box-sizing: border-box;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        padding: 12px;
        font: inherit;
      }
      button {
        margin-top: 10px;
        padding: 10px 14px;
        border: 0;
        border-radius: 6px;
        background: #2563eb;
        color: #ffffff;
        font-weight: 700;
        cursor: pointer;
      }
      #answer {
        margin-top: 16px;
        white-space: pre-wrap;
        line-height: 1.5;
      }
    </style>
  </head>
  <body>
    <main>
      <header>
        <h1>FinOps UI Agent</h1>
        <p>Ops VPC에서 비용 현황을 보고 채팅으로 분석 요청을 입력하는 UI입니다.</p>
      </header>
      <section class="grid">
        <div class="card"><div class="label">Monthly cost trend</div><div class="value">+8.4%</div></div>
        <div class="card"><div class="label">Idle compute</div><div class="value">3 groups</div></div>
        <div class="card"><div class="label">RDS utilization</div><div class="value">22%</div></div>
      </section>
      <section class="chat">
        <h2>Chat Prompt</h2>
        <textarea id="prompt" placeholder="예: 이번 달 비용 증가 원인을 요약해줘"></textarea>
        <button onclick="sendPrompt()">Send</button>
        <div id="answer"></div>
      </section>
    </main>
    <script>
      async function sendPrompt() {
        const prompt = document.getElementById("prompt").value;
        const answer = document.getElementById("answer");
        answer.textContent = "분석 중...";
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({prompt})
        });
        const data = await res.json();
        answer.textContent = `${data.answer}\\n\\n추천 작업:\\n- ${data.suggested_actions.join("\\n- ")}`;
      }
    </script>
  </body>
</html>
"""
