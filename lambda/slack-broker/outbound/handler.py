"""
financial-slack-outbound Lambda
================================
outbound SQS(financial-slack-hitl-outbound)의 메시지를 소비해 Slack
chat.postMessage를 호출한다. slack_sdk 등 외부 패키지 없이 표준 라이브러리
(urllib)만으로 HTTPS POST를 수행한다(전송 계층만).

메시지 바디(JSON)는 chat.postMessage 파라미터(channel/text/blocks 등)를 그대로
담은 객체로 가정한다. 메시지를 만드는 쪽(bot.py 등)의 변경은 이번 작업 범위 밖.

필요 환경변수(Terraform이 주입):
    SLACK_HITL_SECRET_ARN   financial-slack-hitl-tokens 시크릿 ARN
                            (slack_bot_token 키를 읽는다)
"""

from __future__ import annotations

import json
import os
import urllib.request

import boto3

SECRET_ARN = os.environ["SLACK_HITL_SECRET_ARN"]
SLACK_API_URL = "https://slack.com/api/chat.postMessage"

# 콜드 스타트 간 재사용 — 호출마다 Secrets Manager를 다시 조회하지 않도록 캐시
_bot_token_cache: str | None = None

_secrets_client = boto3.client("secretsmanager")


def _get_bot_token() -> str:
    """financial-slack-hitl-tokens 시크릿의 slack_bot_token 키 조회(콜드 스타트당 1회)."""
    global _bot_token_cache
    if _bot_token_cache is None:
        resp = _secrets_client.get_secret_value(SecretId=SECRET_ARN)
        secret = json.loads(resp["SecretString"])
        _bot_token_cache = secret["slack_bot_token"]
    return _bot_token_cache


def _post_message(payload: dict) -> None:
    """payload를 그대로 chat.postMessage 요청 바디로 사용해 Slack Web API 호출."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        SLACK_API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_get_bot_token()}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        if not result.get("ok"):
            # Slack API는 HTTP 200과 함께 {"ok": false, "error": ...}를 반환할 수 있음
            # (예: invalid_auth, channel_not_found) — 예외로 승격해 SQS 재시도/DLQ 유도
            raise RuntimeError(f"slack chat.postMessage failed: {result.get('error')}")


def lambda_handler(event: dict, _context) -> None:
    """outbound SQS event source mapping 트리거.

    배치 내 메시지를 순서대로 처리한다. 실패 시 예외를 그대로 올려 Lambda가 해당
    배치를 재시도(→ maxReceiveCount 초과 시 DLQ)하도록 둔다.
    """
    for record in event.get("Records", []):
        payload = json.loads(record["body"])
        _post_message(payload)
