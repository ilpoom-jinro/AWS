"""
Slack HITL 봇 — mas/slack-hitl/bot.py  (계약이 가리키던 위치)
============================================================
공통 컴포넌트. 3개 시나리오(FinOps/AIOps/SecOps) 워크플로우가 전부 이 봇으로 승인받는다.

두 가지를 동시에 한다:
  ① Temporal 워커  : 공통 Activity `send_approval_request` / `send_reminder` 를 등록.
                     워크플로우가 호출하면 슬랙에 승인/거부 버튼 메시지를 올리고 티켓 반환.
  ② Slack Socket Mode 리스너 : 버튼 클릭 이벤트를 받아 해당 워크플로우에 `submit_approval`
                     시그널을 쏜다. (우리 signal_approval.py가 하던 일을 진짜 슬랙으로)

봇은 특정 워크플로우 클래스에 의존하지 않는다 — 시그널을 **이름("submit_approval")**으로
보내므로 3개 시나리오가 같은 이름·시그니처의 시그널만 노출하면 공용으로 쓰인다.

전용 task queue(HITL_TASK_QUEUE)에서 돈다. 워크플로우는 이 큐로 승인 Activity를 라우팅한다.

필요 환경변수:
    SLACK_BOT_TOKEN   xoxb-...   (Bot User OAuth Token)
    SLACK_APP_TOKEN   xapp-...   (App-Level Token, Socket Mode)
    SLACK_CHANNEL_ID  C...       (승인 메시지 올릴 채널)
    TEMPORAL_ADDRESS  (기본 localhost:7233)
    HITL_TASK_QUEUE   (기본 hitl-approval-queue — 워크플로우와 반드시 동일)

설치:  pip install slack_bolt aiohttp temporalio
실행 (mas/ 에서):  python slack-hitl/bot.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# mas/ 를 import 경로에 (이 파일은 mas/slack-hitl/bot.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from contracts.models import ApprovalRequest, ApprovalTicket

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
HITL_TASK_QUEUE = os.getenv("HITL_TASK_QUEUE", "hitl-approval-queue")

_slack = AsyncWebClient(token=SLACK_BOT_TOKEN)
_temporal_client: Client | None = None


# =====================================================================
# Slack 메시지 구성 / 페이로드 파싱 (네트워크 없는 순수 함수 — 테스트 가능)
# =====================================================================
def build_approval_blocks(request: ApprovalRequest, temporal_workflow_id: str) -> list[dict]:
    """승인/거부 버튼 메시지 블록. 버튼 value에 Temporal workflow id를 심는다."""
    value = json.dumps({"wf": temporal_workflow_id})
    return [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"🔐 보안 승인 요청 [{request.severity.upper()}]"}},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*{request.summary}*\n{request.detail}"}},
        {"type": "context",
         "elements": [{"type": "mrkdwn",
                       "text": f"scenario: `{request.scenario}` · workflow: `{temporal_workflow_id}`"}]},
        {"type": "actions", "block_id": "hitl_actions", "elements": [
            {"type": "button", "action_id": "hitl_approve", "style": "primary",
             "text": {"type": "plain_text", "text": "✅ 승인"}, "value": value},
            {"type": "button", "action_id": "hitl_reject", "style": "danger",
             "text": {"type": "plain_text", "text": "⛔ 거부"}, "value": value},
        ]},
    ]


def parse_action_value(value: str) -> str:
    """버튼 value(JSON)에서 Temporal workflow id 추출."""
    return json.loads(value)["wf"]


def decision_text(approved: bool, reviewer_slack_id: str) -> str:
    return f"{'✅ 승인됨' if approved else '⛔ 거부됨'} — by <@{reviewer_slack_id}>"


# =====================================================================
# 공통 Temporal Activities (봇이 소유 — 계약: SecOpsActivities/CommonActivities)
# =====================================================================
@activity.defn(name="send_approval_request")
async def send_approval_request(request: ApprovalRequest) -> ApprovalTicket:
    """슬랙에 승인 요청 메시지 게시 후 티켓 반환. 즉시 반환(대기는 워크플로우가 signal로)."""
    wf_id = activity.info().workflow_id          # 호출한 워크플로우의 Temporal id
    resp = await _slack.chat_postMessage(
        channel=SLACK_CHANNEL_ID,
        blocks=build_approval_blocks(request, wf_id),
        text=f"보안 승인 요청: {request.summary}",   # 알림/폴백 텍스트
    )
    return ApprovalTicket(
        workflow_id=request.workflow_id,
        slack_message_ts=resp["ts"],
        channel_id=resp["channel"],
    )


@activity.defn(name="send_reminder")
async def send_reminder(ticket: ApprovalTicket) -> None:
    """리마인더 — 원 메시지 스레드에 재알림."""
    await _slack.chat_postMessage(
        channel=ticket.channel_id,
        thread_ts=ticket.slack_message_ts,
        text="⏰ 아직 미결입니다. 승인/거부를 기다리고 있어요.",
    )


# =====================================================================
# Slack 버튼 → Temporal signal
# =====================================================================
async def _signal_decision(body: dict, approved: bool) -> None:
    wf_id = parse_action_value(body["actions"][0]["value"])
    reviewer = body["user"]["id"]
    assert _temporal_client is not None
    handle = _temporal_client.get_workflow_handle(wf_id)
    # 시그널 이름으로 호출 → 봇은 워크플로우 클래스에 의존하지 않음 (3 시나리오 공통)
    await handle.signal("submit_approval", args=[approved, reviewer, "via slack"])


async def _update_message(body: dict, approved: bool) -> None:
    """결정 후 버튼 제거 + 결과 표시 (중복 클릭 방지)."""
    await _slack.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=decision_text(approved, body["user"]["id"]),
        blocks=[{"type": "section",
                 "text": {"type": "mrkdwn", "text": decision_text(approved, body["user"]["id"])}}],
    )


def register_handlers(app: AsyncApp) -> None:
    @app.action("hitl_approve")
    async def _on_approve(ack, body):  # noqa: ANN001
        await ack()
        await _signal_decision(body, True)
        await _update_message(body, True)

    @app.action("hitl_reject")
    async def _on_reject(ack, body):  # noqa: ANN001
        await ack()
        await _signal_decision(body, False)
        await _update_message(body, False)


# =====================================================================
# main: Temporal 워커 + Slack Socket Mode 동시 실행
# =====================================================================
async def main() -> None:
    global _temporal_client
    missing = [k for k in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL_ID")
               if not os.getenv(k)]
    if missing:
        raise SystemExit(f"환경변수 누락: {', '.join(missing)}")

    _temporal_client = await Client.connect(TEMPORAL_ADDRESS, data_converter=pydantic_data_converter)
    worker = Worker(
        _temporal_client,
        task_queue=HITL_TASK_QUEUE,
        activities=[send_approval_request, send_reminder],
    )
    app = AsyncApp(token=SLACK_BOT_TOKEN)
    register_handlers(app)
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)

    print(f"[slack-hitl] Temporal 워커(queue='{HITL_TASK_QUEUE}') + Slack Socket Mode 시작. Ctrl+C로 종료.")
    async with worker:
        await handler.start_async()   # 소켓 연결 유지하며 버튼 이벤트 수신


if __name__ == "__main__":
    asyncio.run(main())
