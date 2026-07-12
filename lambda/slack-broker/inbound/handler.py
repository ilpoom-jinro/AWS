"""
financial-slack-inbound Lambda
===============================
Slack Interactivity 콜백(API Gateway REST API, Lambda proxy 통합)을 받아 서명을
검증하고, 검증된 원본 payload만 inbound SQS(financial-slack-hitl-inbound)로
전달한다.

전송 계층만 담당 — Temporal signal 변환, 시나리오 분기(aiops/secops/finops) 등
실제 처리 로직은 여기서 하지 않는다(별도 in-cluster poller 단계에서 구현 예정).

필요 환경변수(Terraform이 주입):
    SLACK_HITL_SECRET_ARN   financial-slack-hitl-tokens 시크릿 ARN
                            (signing_secret 키를 읽는다)
    INBOUND_QUEUE_URL       financial-slack-hitl-inbound 큐 URL
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse

import boto3

SECRET_ARN = os.environ["SLACK_HITL_SECRET_ARN"]
INBOUND_QUEUE_URL = os.environ["INBOUND_QUEUE_URL"]

# Slack 리플레이 방지 허용 오차(초) — Slack 공식 권장값 5분
MAX_TIMESTAMP_SKEW_SECONDS = 60 * 5

# 콜드 스타트 간 재사용 — 호출마다 Secrets Manager를 다시 조회하지 않도록 캐시
_signing_secret_cache: str | None = None

_secrets_client = boto3.client("secretsmanager")
_sqs_client = boto3.client("sqs")


def _get_signing_secret() -> str:
    """financial-slack-hitl-tokens 시크릿의 signing_secret 키 조회(콜드 스타트당 1회)."""
    global _signing_secret_cache
    if _signing_secret_cache is None:
        resp = _secrets_client.get_secret_value(SecretId=SECRET_ARN)
        secret = json.loads(resp["SecretString"])
        _signing_secret_cache = secret["signing_secret"]
    return _signing_secret_cache


def _get_header(headers: dict, name: str) -> str | None:
    """API Gateway REST API는 헤더 키 대소문자를 그대로 전달하므로 대소문자 무시 조회."""
    if not headers:
        return None
    lowered = {k.lower(): v for k, v in headers.items()}
    return lowered.get(name.lower())


def _is_valid_signature(headers: dict, raw_body: str) -> bool:
    """Slack v0 서명 검증: HMAC-SHA256(signing_secret, "v0:{ts}:{body}") 상수시간 비교.

    X-Slack-Request-Timestamp가 현재 시각과 5분 넘게 차이나면 리플레이로 간주해 거부.
    """
    timestamp = _get_header(headers, "X-Slack-Request-Timestamp")
    signature = _get_header(headers, "X-Slack-Signature")
    if not timestamp or not signature:
        return False

    try:
        if abs(time.time() - int(timestamp)) > MAX_TIMESTAMP_SKEW_SECONDS:
            return False
    except ValueError:
        return False

    basestring = f"v0:{timestamp}:{raw_body}".encode("utf-8")
    signing_secret = _get_signing_secret().encode("utf-8")
    computed = "v0=" + hmac.new(signing_secret, basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


def _extract_payload(headers: dict, raw_body: str) -> str | None:
    """application/x-www-form-urlencoded 바디에서 payload 필드(JSON 문자열)를 꺼낸다.

    Slack Interactivity 콜백은 폼 인코딩된 바디의 payload 필드에 실제 이벤트(JSON)를 담아 보낸다.
    """
    content_type = _get_header(headers, "Content-Type") or ""
    if "application/x-www-form-urlencoded" not in content_type:
        return None
    parsed = urllib.parse.parse_qs(raw_body)
    values = parsed.get("payload")
    if not values:
        return None
    return values[0]


def lambda_handler(event: dict, _context) -> dict:
    """API Gateway Lambda 프록시 통합 핸들러.

    Slack Interactivity 3초 응답 규칙을 지키기 위해 서명 검증 → SQS enqueue 후
    곧바로 200을 반환한다. 실제 승인/거부 처리는 기다리지 않는다(비동기).
    """
    headers = event.get("headers") or {}
    raw_body = event.get("body") or ""

    # API Gateway가 바이너리 미디어 타입 설정 등으로 base64 인코딩해 전달한 경우 복원
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")

    if not _is_valid_signature(headers, raw_body):
        return {"statusCode": 401, "body": "invalid signature"}

    payload = _extract_payload(headers, raw_body)
    if payload is None:
        return {"statusCode": 400, "body": "missing payload field"}

    _sqs_client.send_message(QueueUrl=INBOUND_QUEUE_URL, MessageBody=payload)

    return {"statusCode": 200, "body": ""}
