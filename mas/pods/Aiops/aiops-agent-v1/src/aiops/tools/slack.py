"""
tools/slack.py — Slack WebAPI 래퍼

[v0.2 수정사항]
- 기존: 각 노드 모듈이 import 시점에 SlackClient(settings.SLACK_BOT_TOKEN) 생성
  → Secrets Manager 로드(load_secrets)는 FastAPI lifespan에서 호출되므로
    import 시점에는 토큰이 빈 문자열 → 모든 Slack 호출이 invalid_auth로 실패
- 수정: get_slack() lazy singleton. 첫 호출 시점(= 토큰 로드 후)에 생성.
"""
from __future__ import annotations

import logging
from typing import Any

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

_singleton: "SlackClient | None" = None


def get_slack() -> "SlackClient":
    """토큰 로드 이후 첫 호출 시점에 클라이언트 생성 (lazy singleton)"""
    global _singleton
    if _singleton is None:
        from ..config import settings
        _singleton = SlackClient(settings.SLACK_BOT_TOKEN)
    return _singleton


class SlackClient:
    def __init__(self, token: str) -> None:
        if not token:
            logger.warning("Slack 토큰이 비어 있습니다 — 메시지 발송이 실패합니다.")
        self._client = AsyncWebClient(token=token)

    async def post_message(self, channel: str, text: str) -> None:
        """단순 텍스트 메시지 발송 (실패해도 에이전트는 계속 동작)"""
        try:
            await self._client.chat_postMessage(channel=channel, text=text)
        except SlackApiError as exc:
            logger.error("Slack postMessage 실패: %s", exc.response.get("error"))
        except Exception as exc:
            logger.error("Slack postMessage 예외: %s", exc)

    async def post_blocks(
        self, channel: str, blocks: list[dict[str, Any]], text: str = ""
    ) -> str | None:
        """Block Kit 메시지 발송, ts(타임스탬프) 반환"""
        try:
            resp = await self._client.chat_postMessage(
                channel=channel,
                blocks=blocks,
                text=text or "AIOps 알림",
            )
            return resp.get("ts")
        except SlackApiError as exc:
            logger.error("Slack postBlocks 실패: %s", exc.response.get("error"))
            return None
        except Exception as exc:
            logger.error("Slack postBlocks 예외: %s", exc)
            return None

    async def update_message(self, channel: str, ts: str, text: str) -> None:
        """기존 메시지 업데이트 (승인/거부 후 버튼 제거용)"""
        try:
            await self._client.chat_update(
                channel=channel, ts=ts, text=text, blocks=[]
            )
        except SlackApiError as exc:
            logger.error("Slack update 실패: %s", exc.response.get("error"))


def build_approval_blocks(
    pod: str,
    root_cause: str,
    strategy: str,
    command: list[str],
    callback_id: str,
) -> list[dict[str, Any]]:
    """승인 요청 Block Kit 메시지. callback_id는 actions 블록의 block_id."""
    cmd_str = " ".join(command)
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 AIOps — 장애 감지 및 복구 승인 요청",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*장애 파드*\n`{pod}`"},
                {"type": "mrkdwn", "text": f"*감지된 원인*\n{root_cause}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*제안 복구 전략*: `{strategy.upper()}`\n"
                    f"*실행 명령어*:\n```{cmd_str}```"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": callback_id,
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ 승인"},
                    "style": "primary",
                    "value": "approve",
                    "action_id": "approve",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ 거부"},
                    "style": "danger",
                    "value": "reject",
                    "action_id": "reject",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "⏰ 30분 내 미응답 시 자동 취소됩니다.",
                }
            ],
        },
    ]
