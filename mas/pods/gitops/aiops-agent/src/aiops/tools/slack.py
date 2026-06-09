"""
tools/slack.py — Slack WebAPI 래퍼
Slack SDK를 통해 인터랙티브 메시지(Block Kit)를 발송하고
/slack/actions WebHook 콜백을 통해 승인/거부 결과를 수신한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class SlackClient:
    def __init__(self, token: str) -> None:
        self._client = AsyncWebClient(token=token)

    async def post_message(self, channel: str, text: str) -> None:
        """단순 텍스트 메시지 발송"""
        try:
            await self._client.chat_postMessage(channel=channel, text=text)
        except SlackApiError as exc:
            logger.error("Slack postMessage 실패: %s", exc.response["error"])

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
            logger.error("Slack postBlocks 실패: %s", exc.response["error"])
            return None

    async def update_message(
        self, channel: str, ts: str, text: str
    ) -> None:
        """기존 메시지 업데이트 (승인/거부 후 버튼 제거용)"""
        try:
            await self._client.chat_update(
                channel=channel, ts=ts, text=text, blocks=[]
            )
        except SlackApiError as exc:
            logger.error("Slack update 실패: %s", exc.response["error"])


def build_approval_blocks(
    pod: str,
    root_cause: str,
    strategy: str,
    command: list[str],
    callback_id: str,
) -> list[dict[str, Any]]:
    """
    승인 요청 Block Kit 메시지 구성.
    callback_id는 block_id로 사용되어 WebHook에서 식별에 쓰인다.
    """
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
