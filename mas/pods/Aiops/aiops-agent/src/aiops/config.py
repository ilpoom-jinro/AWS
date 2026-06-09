"""
config.py — 환경변수 기반 설정
AWS Secrets Manager에서 민감값을 자동으로 로드한다.
"""
from __future__ import annotations

import json
import os

import boto3
from pydantic import Field
from pydantic_settings import BaseSettings


def _get_secret(secret_id: str, region: str) -> str:
    """Secrets Manager에서 평문 또는 JSON 문자열 반환"""
    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_id)
    return resp.get("SecretString", "")


class Settings(BaseSettings):
    # ── AWS ─────────────────────────────────────────────────────────
    AWS_REGION: str = Field(default="ap-northeast-2")

    # ── EKS 컨텍스트 ───────────────────────────────────────────────
    OPS_KUBE_CONTEXT: str = Field(default="financial-ops-eks")
    SERVICE_KUBE_CONTEXT: str = Field(default="financial-service-eks")

    # ── Prometheus ────────────────────────────────────────────────
    PROMETHEUS_URL: str = Field(
        default="http://prometheus-server.monitoring.svc.cluster.local:80"
    )

    # ── Bedrock ───────────────────────────────────────────────────
    BEDROCK_MODEL_ID: str = Field(
        default="anthropic.claude-3-5-sonnet-20241022-v2:0"
    )

    # ── Slack ─────────────────────────────────────────────────────
    SLACK_CHANNEL: str = Field(default="#ops-alerts")
    SLACK_BOT_TOKEN: str = Field(default="")          # Secrets Manager에서 주입
    SLACK_SECRET_ID: str = Field(default="aiops/slack-bot-token")

    # ── 동작 파라미터 ─────────────────────────────────────────────
    SCAN_INTERVAL_SEC: int = Field(default=30)         # 모니터링 주기 (초)
    VERIFY_WAIT_SEC: int = Field(default=300)          # 복구 후 검증 대기 (5분)
    APPROVAL_TIMEOUT_SEC: int = Field(default=1800)    # Slack 승인 타임아웃 (30분)
    CRASH_THRESHOLD: int = Field(default=3)            # CrashLoop 감지 재시작 횟수
    PENDING_TIMEOUT_SEC: int = Field(default=600)      # Pending 허용 시간 (10분)
    RCA_CONFIDENCE_MIN: float = Field(default=0.7)     # 자동 조치 최소 신뢰도

    # ── FastAPI 서버 ──────────────────────────────────────────────
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8080)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def load_secrets(self) -> None:
        """Secrets Manager에서 민감값 로드 (파드 기동 시 1회 호출)"""
        if not self.SLACK_BOT_TOKEN and self.SLACK_SECRET_ID:
            try:
                raw = _get_secret(self.SLACK_SECRET_ID, self.AWS_REGION)
                # JSON {"token": "xoxb-..."} 또는 평문 모두 지원
                try:
                    data = json.loads(raw)
                    self.SLACK_BOT_TOKEN = data.get("token", raw)
                except json.JSONDecodeError:
                    self.SLACK_BOT_TOKEN = raw
            except Exception as exc:
                print(f"[config] Secrets Manager 로드 실패: {exc}")


settings = Settings()
