"""
Slack HITL 봇 — mas/pods/platform/slack-hitl/bot.py  (계약이 가리키던 위치)
============================================================
공통 컴포넌트. 3개 시나리오(FinOps/AIOps/SecOps) 워크플로우가 전부 이 봇으로 승인받는다.

두 가지를 동시에 한다:
  ① Temporal 워커  : 공통 Activity `send_approval_request` / `send_reminder` 를 등록.
                     워크플로우가 호출하면 슬랙에 승인/거부 버튼 메시지를 올리고 티켓 반환.
  ② Slack Socket Mode 리스너 : 버튼 클릭 이벤트를 받아 해당 워크플로우에 시나리오별
                     시그널을 쏜다.

시나리오별 signal 이름·페이로드 (워크플로우 구현과 반드시 정합):
  aiops  → signal "approval_result",  args=[ApprovalResult(...)]
  secops → signal "submit_approval",  args=[bool, reviewer_id, reason]
  (FinOps는 REST /approve 엔드포인트 방식 → 이 봇 미사용)

전용 task queue(HITL_TASK_QUEUE)에서 돈다. 워크플로우는 이 큐로 승인 Activity를 라우팅한다.

필요 환경변수:
    SLACK_BOT_TOKEN   xoxb-...   (Bot User OAuth Token)
    SLACK_APP_TOKEN   xapp-...   (App-Level Token, Socket Mode)
    SLACK_CHANNEL_ID  C...       (승인 메시지 올릴 채널)
    TEMPORAL_ADDRESS  (기본 localhost:7233)
    HITL_TASK_QUEUE   (기본 hitl-approval-queue — 워크플로우와 반드시 동일)

설치:  pip install slack_bolt aiohttp temporalio
실행 (mas/ 에서):  python pods/platform/slack-hitl/bot.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# mas/ 를 import 경로에 (이 파일은 mas/pods/platform/slack-hitl/bot.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from contracts.models import ApprovalRequest, ApprovalResult, ApprovalTicket

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
    """승인/거부 버튼 메시지 블록.
    버튼 value에 workflow id와 scenario를 심는다 — 클릭 시 시나리오별 signal 분기에 사용.
    """
    value = json.dumps({"wf": temporal_workflow_id, "scenario": request.scenario})
    title_by_scenario = {
        "aiops": "AIOps 복구 승인 요청",
        "secops": "보안 승인 요청",
        "finops": "FinOps 승인 요청",
    }
    title = title_by_scenario.get(request.scenario, "승인 요청")
    return [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"🔐 {title} [{request.severity.upper()}]"}},
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


def parse_action_value(value: str) -> tuple[str, str]:
    """버튼 value(JSON)에서 (workflow_id, scenario) 추출."""
    data = json.loads(value)
    return data["wf"], data.get("scenario", "secops")


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
        text=f"승인 요청: {request.summary}",   # 알림/폴백 텍스트
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
# Slack 버튼 → Temporal signal (시나리오별 분기)
# =====================================================================
async def _signal_decision(body: dict, approved: bool) -> None:
    wf_id, scenario = parse_action_value(body["actions"][0]["value"])
    reviewer = body["user"]["id"]
    assert _temporal_client is not None
    handle = _temporal_client.get_workflow_handle(wf_id)

    if scenario == "aiops":
        # AIOps: signal "approval_result", 페이로드는 ApprovalResult 모델
        # workflow_id = wf_id (Temporal native ID == domain workflow_id, 설계 규칙)
        result = ApprovalResult(
            workflow_id=wf_id,
            approved=approved,
            reviewer_id=reviewer,
        )
        await handle.signal("approval_result", args=[result])
    else:
        # SecOps (기본): signal "submit_approval", positional args
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
        await _handle_decision(body, True)

    @app.action("hitl_reject")
    async def _on_reject(ack, body):  # noqa: ANN001
        await ack()
        await _handle_decision(body, False)


async def _handle_decision(body: dict, approved: bool) -> None:
    """
    signal 전송 + 메시지 업데이트를 묶어서 처리하며 실패를 안전하게 처리한다.

    실패 케이스별 대응:
      - Temporal workflow 만료/없음 : 메시지를 "이미 처리됨 또는 만료" 로 갱신
      - 그 외 signal 오류            : 메시지를 "처리 중 오류" 로 갱신
      - 메시지 업데이트 실패         : 로그만 남기고 조용히 처리 (Slack 쪽 문제)
    """
    try:
        await _signal_decision(body, approved)
    except Exception as exc:
        error_str = str(exc)
        # 만료된 workflow, 존재하지 않는 workflow_id 등
        if any(kw in error_str for kw in ("not found", "workflow not found",
                                           "already completed", "terminated")):
            label = "⚠️ 이미 처리됐거나 만료된 요청입니다."
        else:
            label = f"❌ 처리 중 오류 발생: {error_str[:120]}"

        try:
            await _slack.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text=label,
                blocks=[{"type": "section",
                         "text": {"type": "mrkdwn", "text": label}}],
            )
        except Exception:
            pass  # Slack 업데이트 실패는 무시 (봇 입장에서 할 수 있는 게 없음)
        return

    # signal 성공 → 버튼 제거 + 결정 결과 표시
    try:
        await _update_message(body, approved)
    except Exception:
        pass  # 메시지 업데이트 실패는 무시 (결정 자체는 이미 전달됨)


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
