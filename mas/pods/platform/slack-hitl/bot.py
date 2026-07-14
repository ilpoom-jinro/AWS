"""
Slack HITL 봇 — mas/pods/platform/slack-hitl/bot.py  (계약이 가리키던 위치)
============================================================
공통 컴포넌트. AIOps/SecOps 워크플로우가 이 봇으로 승인받는다.
(FinOps는 현재 REST /approve 엔드포인트 방식 → 이 봇 미사용. 다만 공용 브로커로서
scenario="finops" 채널 매핑은 미리 준비해둔다 — SCENARIO_CHANNELS/build_approval_blocks의
title_by_scenario 참고. FinOps가 이 경로로 들어오면 바로 쓸 수 있음)

2단계(SQS 라우터 전환) 이후 세 가지를 한다:
  ① Temporal 워커  : 공통 Activity `send_approval_request` / `send_reminder` 를 등록.
                     워크플로우가 호출하면 outbound SQS에 Slack 메시지 요청을 올리고
                     티켓 반환(실제 Slack 게시는 financial-slack-outbound Lambda가 수행).
  ② inbound SQS 폴링 : financial-slack-hitl-inbound 큐를 롱폴링해 Slack 버튼 클릭
                     payload(financial-slack-inbound Lambda가 서명 검증 후 넣어준 것)를
                     받아 해당 워크플로우에 시나리오별 시그널을 쏜다.
  ③ ①·②를 같은 asyncio 이벤트루프에서 동시 실행.

Socket Mode는 더 이상 쓰지 않는다 — ops VPC(격리망, IGW/NAT 없음)에서 slack.com에
직접 못 붙는 문제를, API Gateway + Lambda 2개 + SQS 2개로 구성된 공용 브로커
(slack-broker.tf)가 대신 처리한다. bot.py는 그 브로커의 SQS 큐만 상대한다.

시나리오별 signal 이름·페이로드 (워크플로우 구현과 반드시 정합):
  aiops  → signal "approval_result",  args=[ApprovalResult(...)]
  secops → signal "submit_approval",  args=[bool, reviewer_id, reason]

전용 task queue(HITL_TASK_QUEUE)에서 돈다. 워크플로우는 이 큐로 승인 Activity를 라우팅한다.

필요 환경변수:
    SLACK_CHANNEL_SECOPS C...       (secops 시나리오 승인 메시지 채널)
    SLACK_CHANNEL_AIOPS  C...       (aiops 시나리오 승인 메시지 채널)
    SLACK_CHANNEL_FINOPS C...       (finops 시나리오 승인 메시지 채널 — 현재 미사용, 대비용)
    TEMPORAL_ADDRESS     (기본 localhost:7233)
    HITL_TASK_QUEUE      (기본 hitl-approval-queue — 워크플로우와 반드시 동일)
    OUTBOUND_QUEUE_URL   financial-slack-hitl-outbound SQS 큐 URL
                         (Slack 게시/갱신 요청을 이 큐로 올림 — 실제 호출은 outbound Lambda)
    INBOUND_QUEUE_URL    financial-slack-hitl-inbound SQS 큐 URL
                         (Slack 버튼 클릭 payload를 이 큐에서 폴링)

SLACK_BOT_TOKEN/SLACK_APP_TOKEN은 더 이상 이 프로세스에 필요 없다 — 봇은 Slack API를
직접 호출하지 않는다(전부 outbound Lambda가 자기 몫의 시크릿으로 처리).

설치:  pip install boto3 temporalio
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

import boto3
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from contracts.models import ApprovalRequest, ApprovalResult, ApprovalTicket

# 공용 브로커라 시나리오별로 다른 채널에 카드를 보낸다 — 단일 SLACK_CHANNEL_ID 고정 폐기.
SCENARIO_CHANNELS = {
    "secops": os.getenv("SLACK_CHANNEL_SECOPS"),
    "aiops": os.getenv("SLACK_CHANNEL_AIOPS"),
    "finops": os.getenv("SLACK_CHANNEL_FINOPS"),
}
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
HITL_TASK_QUEUE = os.getenv("HITL_TASK_QUEUE", "hitl-approval-queue")
OUTBOUND_QUEUE_URL = os.getenv("OUTBOUND_QUEUE_URL")
INBOUND_QUEUE_URL = os.getenv("INBOUND_QUEUE_URL")

_sqs = boto3.client("sqs")
_temporal_client: Client | None = None


def _channel_for_scenario(scenario: str) -> str:
    """scenario → Slack 채널 ID 조회. 매핑에 없는 scenario나 env 미설정 시 조용히
    엉뚱한 채널로 보내지 않고 즉시 에러를 낸다(Temporal Activity 실패로 표면화됨)."""
    if scenario not in SCENARIO_CHANNELS:
        raise ValueError(f"알 수 없는 scenario '{scenario}' — SCENARIO_CHANNELS에 매핑 없음")
    channel = SCENARIO_CHANNELS[scenario]
    if not channel:
        raise ValueError(f"scenario '{scenario}'에 대응하는 채널 env가 설정되지 않음")
    return channel


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


def _approved_from_body(body: dict) -> bool:
    """Slack block_actions payload의 action_id로 승인/거부 판별.

    Socket Mode 시절엔 @app.action("hitl_approve")/("hitl_reject") 핸들러가 각각
    approved=True/False를 고정해서 넘겼다(register_handlers, 제거됨). 라우터 전환 후엔
    이 봇이 직접 action_id를 보고 판별해야 한다.
    """
    action_id = body["actions"][0]["action_id"]
    return action_id == "hitl_approve"


# =====================================================================
# outbound SQS — 실제 Slack API 호출은 financial-slack-outbound Lambda가 수행.
# 여기서는 요청 payload를 큐에 올리기만 한다(blocking boto3 호출은 스레드로 오프로드 —
# mas/pods/secops/orchestrator/app/poller.py와 동일 패턴).
# =====================================================================
async def _enqueue_outbound(payload: dict) -> None:
    await asyncio.to_thread(
        _sqs.send_message,
        QueueUrl=OUTBOUND_QUEUE_URL,
        MessageBody=json.dumps(payload),
    )


# =====================================================================
# 공통 Temporal Activities (봇이 소유 — 계약: SecOpsActivities/CommonActivities)
# =====================================================================
@activity.defn(name="send_approval_request")
async def send_approval_request(request: ApprovalRequest) -> ApprovalTicket:
    """승인 요청 메시지를 scenario에 맞는 채널의 outbound SQS에 올린 뒤 티켓 반환.
    즉시 반환(대기는 워크플로우가 signal로).

    채널은 request.scenario로 SCENARIO_CHANNELS에서 조회한다 — 매핑에 없거나 env가
    비어있으면 _channel_for_scenario가 예외를 던져 Activity 자체가 실패한다(잘못된
    채널로 조용히 새지 않도록).

    알려진 갭: 실제 Slack 게시는 outbound Lambda가 비동기로 수행하므로, 여기서는
    Slack이 부여할 ts를 알 방법이 없다 — slack_message_ts를 빈 문자열로 둔다.
    (영향: send_reminder가 스레드 답글 대신 새 메시지로 나감 — 아래 send_reminder 참고)
    """
    wf_id = activity.info().workflow_id          # 호출한 워크플로우의 Temporal id
    channel = _channel_for_scenario(request.scenario)
    await _enqueue_outbound({
        "channel": channel,
        "blocks": build_approval_blocks(request, wf_id),
        "text": f"승인 요청: {request.summary}",   # 알림/폴백 텍스트
    })
    return ApprovalTicket(
        workflow_id=request.workflow_id,
        slack_message_ts="",
        channel_id=channel,
    )


@activity.defn(name="send_reminder")
async def send_reminder(ticket: ApprovalTicket) -> None:
    """리마인더 — 원 메시지 스레드에 재알림.

    send_approval_request가 slack_message_ts를 채우지 못하는 현재 구조상, ts가
    없으면 스레드 답글이 아니라 채널에 새 메시지로 보낸다(하위호환 — 에러로 만들지 않음).
    """
    payload = {
        "channel": ticket.channel_id,
        "text": "⏰ 아직 미결입니다. 승인/거부를 기다리고 있어요.",
    }
    if ticket.slack_message_ts:
        payload["thread_ts"] = ticket.slack_message_ts
    await _enqueue_outbound(payload)


@activity.defn(name="send_action_result")
async def send_action_result(ticket: ApprovalTicket, message: str) -> None:
    """대응 실행 결과 통지 — 버튼 없는 일반 메시지, 원 카드 스레드에 게시.
    send_reminder와 동일 패턴(카드 재사용 없이 채널/스레드에 텍스트만 전송)."""
    payload = {
        "channel": ticket.channel_id,
        "text": message,
    }
    if ticket.slack_message_ts:
        payload["thread_ts"] = ticket.slack_message_ts
    await _enqueue_outbound(payload)


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


def _blocks_with_status(body: dict, status_text: str) -> list[dict]:
    """원본 카드(header/section/context 등)는 그대로 두고 actions(버튼) 블록만
    상태 표시 section으로 교체한다.

    body["message"]["blocks"]가 없거나 비어있으면(예외 상황 대비) 기존처럼
    section 1개짜리로 안전하게 대체한다.
    """
    original_blocks = body.get("message", {}).get("blocks")
    if not original_blocks:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": status_text}}]

    blocks = [b for b in original_blocks if b.get("type") != "actions"]
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": status_text}})
    return blocks


async def _update_message(body: dict, approved: bool) -> None:
    """결정 후 버튼(actions)만 상태 표시로 교체, 원본 카드는 보존 — outbound SQS에 chat.update 요청."""
    text = decision_text(approved, body["user"]["id"])
    await _enqueue_outbound({
        "method": "update",
        "channel": body["channel"]["id"],
        "ts": body["message"]["ts"],
        "text": text,
        "blocks": _blocks_with_status(body, text),
    })


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
            await _enqueue_outbound({
                "method": "update",
                "channel": body["channel"]["id"],
                "ts": body["message"]["ts"],
                "text": label,
                "blocks": _blocks_with_status(body, label),
            })
        except Exception:
            pass  # outbound enqueue 실패는 무시 (봇 입장에서 할 수 있는 게 없음)
        return

    # signal 성공 → 버튼 제거 + 결정 결과 표시
    try:
        await _update_message(body, approved)
    except Exception:
        pass  # 메시지 업데이트 요청 실패는 무시 (결정 자체는 이미 전달됨)


# =====================================================================
# inbound SQS 폴링 — Slack 버튼 클릭 payload 수신 (Socket Mode 대체)
# financial-slack-inbound Lambda가 서명 검증 후 이 큐에 원본 payload(JSON 문자열)를
# 그대로 넣어준다. mas/pods/secops/orchestrator/app/poller.py와 동일한 롱폴링 패턴.
# =====================================================================
async def poll_inbound_loop() -> None:
    """inbound SQS 롱폴링 루프. 메시지 → signal 처리 → 성공 시에만 삭제(실패 시 재수신 → DLQ)."""
    if not INBOUND_QUEUE_URL:
        print("[slack-hitl] INBOUND_QUEUE_URL 미설정 — inbound poller 비활성")
        return

    print(f"[slack-hitl] inbound poller 시작: {INBOUND_QUEUE_URL}")
    while True:
        resp = await asyncio.to_thread(
            _sqs.receive_message,
            QueueUrl=INBOUND_QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,   # 롱폴링
            VisibilityTimeout=300,
        )
        for msg in resp.get("Messages", []):
            receipt = msg["ReceiptHandle"]
            try:
                body = json.loads(msg["Body"])
                approved = _approved_from_body(body)
                await _handle_decision(body, approved)
                # _handle_decision은 내부 오류를 스스로 흡수하므로(위 함수 참고),
                # 여기까지 오면 signal 성공/실패 여부와 무관하게 메시지를 삭제한다
                # (재시도해도 같은 결과 — 이미 처리됨/만료됨 라벨만 반복 게시됨).
                await asyncio.to_thread(
                    _sqs.delete_message, QueueUrl=INBOUND_QUEUE_URL, ReceiptHandle=receipt
                )
            except Exception as exc:  # noqa: BLE001  파싱 등 실패 → 삭제 안 함(재수신→DLQ)
                print(f"[slack-hitl] inbound 처리 실패, 재시도 예정: {exc}")


# =====================================================================
# main: Temporal 워커 + inbound SQS 폴링 동시 실행
# =====================================================================
async def main() -> None:
    global _temporal_client
    missing = [k for k in ("SLACK_CHANNEL_SECOPS", "SLACK_CHANNEL_AIOPS", "SLACK_CHANNEL_FINOPS",
                           "OUTBOUND_QUEUE_URL", "INBOUND_QUEUE_URL")
               if not os.getenv(k)]
    if missing:
        raise SystemExit(f"환경변수 누락: {', '.join(missing)}")

    _temporal_client = await Client.connect(TEMPORAL_ADDRESS, data_converter=pydantic_data_converter)
    worker = Worker(
        _temporal_client,
        task_queue=HITL_TASK_QUEUE,
        activities=[send_approval_request, send_reminder, send_action_result],
    )

    print(f"[slack-hitl] Temporal 워커(queue='{HITL_TASK_QUEUE}') + inbound SQS 라우터 시작. Ctrl+C로 종료.")
    async with worker:
        await poll_inbound_loop()   # inbound 큐를 계속 폴링하며 버튼 이벤트 수신


if __name__ == "__main__":
    asyncio.run(main())