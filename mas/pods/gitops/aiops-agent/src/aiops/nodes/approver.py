"""
nodes/approver.py — WAIT_APPROVAL 노드
Slack Block Kit 인터랙티브 메시지를 발송하고
버튼 클릭(WebHook) 결과를 asyncio.Future로 대기한다.

승인: approved_plan = plans[0]
거부 또는 타임아웃: approved_plan = None → graph가 monitor로 복귀
"""
from __future__ import annotations

import asyncio
import logging
import time

from ..config import settings
from ..state import AgentState
from ..tools.slack import SlackClient, build_approval_blocks

logger = logging.getLogger(__name__)

_slack = SlackClient(settings.SLACK_BOT_TOKEN)

# callback_id → asyncio.Future (WebHook 핸들러에서 resolve)
_pending_approvals: dict[str, asyncio.Future[bool]] = {}


def resolve_approval(callback_id: str, approved: bool) -> bool:
    """
    /slack/actions 엔드포인트(main.py)에서 호출.
    Future를 resolve해서 대기 중인 approver.run()을 깨운다.
    """
    future = _pending_approvals.get(callback_id)
    if future and not future.done():
        future.set_result(approved)
        return True
    return False


async def run(state: AgentState) -> AgentState:
    """WAIT_APPROVAL 노드 진입점"""
    if not state["plans"]:
        logger.warning("복구 계획 없음 — 승인 스킵")
        return {**state, "approved_plan": None}

    plan = state["plans"][0]  # 최우선 계획

    # 수동 조사 권고면 실행 없이 Slack 알림만 발송
    if plan["strategy"] == "investigate":
        await _slack.post_message(
            settings.SLACK_CHANNEL,
            (
                f"🔍 *AIOps — 수동 조사 필요*\n"
                f"파드: `{state['events'][0]['pod'] if state['events'] else 'unknown'}`\n"
                f"원인: {state['rca_root_cause']}\n"
                f"사유: {plan['reason']}"
            ),
        )
        return {**state, "approved_plan": None}

    # 고유 callback_id 생성
    cb_id = f"aiops_{int(time.time() * 1000)}"
    event = state["events"][0] if state["events"] else {}

    # Block Kit 메시지 발송
    blocks = build_approval_blocks(
        pod=event.get("pod", "unknown"),
        root_cause=state["rca_root_cause"],
        strategy=plan["strategy"],
        command=plan["command"],
        callback_id=cb_id,
    )
    await _slack.post_blocks(
        channel=settings.SLACK_CHANNEL,
        blocks=blocks,
        text=f"AIOps 장애 감지: {event.get('pod', 'unknown')}",
    )

    # Future 등록 후 타임아웃 대기
    loop = asyncio.get_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    _pending_approvals[cb_id] = future

    approved = False
    try:
        approved = await asyncio.wait_for(
            asyncio.shield(future),
            timeout=float(settings.APPROVAL_TIMEOUT_SEC),
        )
        action = "승인" if approved else "거부"
        await _slack.post_message(
            settings.SLACK_CHANNEL,
            f"{'✅' if approved else '❌'} 복구 계획 {action}됨",
        )
    except asyncio.TimeoutError:
        await _slack.post_message(
            settings.SLACK_CHANNEL,
            f"⏰ {settings.APPROVAL_TIMEOUT_SEC // 60}분 타임아웃 — 복구 계획 자동 취소",
        )
    finally:
        _pending_approvals.pop(cb_id, None)

    return {
        **state,
        "approved_plan": plan if approved else None,
        "approval_ts": str(time.time()),
    }
