"""
config.py — 환경변수 기반 설정

[v0.2 수정사항]
- SLACK_SIGNING_SECRET 추가 (WebHook 서명 검증용)
- OPS/SERVICE EKS 클러스터 이름 추가 (entrypoint.sh의 update-kubeconfig용)
- Secrets Manager 로드 시 signing secret도 함께 로드
"""
from __future__ import annotations

import json
import logging

import boto3
from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


def _get_secret(secret_id: str, region: str) -> str:
    """Secrets Manager에서 평문 또는 JSON 문자열 반환"""
    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_id)
    return resp.get("SecretString", "")


class Settings(BaseSettings):
    # ── AWS ─────────────────────────────────────────────────────────
    AWS_REGION: str = Field(default="ap-northeast-2")

    # ── EKS ────────────────────────────────────────────────────────
    # 컨텍스트 이름: entrypoint.sh의 update-kubeconfig --alias와 일치해야 함
    OPS_KUBE_CONTEXT: str = Field(default="financial-ops-eks")
    SERVICE_KUBE_CONTEXT: str = Field(default="financial-service-eks")
    # 실제 EKS 클러스터 이름: terraform output으로 확인 후 ConfigMap에 설정
    OPS_EKS_CLUSTER_NAME: str = Field(default="")
    SERVICE_EKS_CLUSTER_NAME: str = Field(default="")

    # ── Prometheus ────────────────────────────────────────────────
    # [v0.3] Thanos Query (Prometheus 호환 API) — 모니터링 스택 전환 반영
    PROMETHEUS_URL: str = Field(
        default="http://observability-thanos-query.observability.svc.cluster.local:9090"
    )

    # ── Bedrock ───────────────────────────────────────────────────
    BEDROCK_MODEL_ID: str = Field(
        default="anthropic.claude-3-5-sonnet-20241022-v2:0"
    )

    # ── Slack ─────────────────────────────────────────────────────
    SLACK_CHANNEL: str = Field(default="#ops-alerts")
    SLACK_BOT_TOKEN: str = Field(default="")
    SLACK_SIGNING_SECRET: str = Field(default="")
    SLACK_SECRET_ID: str = Field(default="aiops/slack-bot-token")

    # ── 동작 파라미터 ─────────────────────────────────────────────
    SCAN_INTERVAL_SEC: int = Field(default=30)
    VERIFY_WAIT_SEC: int = Field(default=300)
    APPROVAL_TIMEOUT_SEC: int = Field(default=1800)
    CRASH_THRESHOLD: int = Field(default=3)
    PENDING_TIMEOUT_SEC: int = Field(default=600)
    RCA_CONFIDENCE_MIN: float = Field(default=0.7)

    # ── FastAPI 서버 ──────────────────────────────────────────────
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8080)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def load_secrets(self) -> None:
        """Secrets Manager에서 민감값 로드 (파드 기동 시 1회 호출)"""
        if self.SLACK_BOT_TOKEN:
            return  # 이미 env로 주입됨 (로컬 개발)
        if not self.SLACK_SECRET_ID:
            return
        try:
            raw = _get_secret(self.SLACK_SECRET_ID, self.AWS_REGION)
            try:
                data = json.loads(raw)
                self.SLACK_BOT_TOKEN = data.get("token", "")
                # signing secret도 같은 Secret에 함께 저장 가능
                if not self.SLACK_SIGNING_SECRET:
                    self.SLACK_SIGNING_SECRET = data.get("signing_secret", "")
            except json.JSONDecodeError:
                self.SLACK_BOT_TOKEN = raw  # 평문 토큰
        except Exception as exc:
            logger.error("Secrets Manager 로드 실패: %s", exc)


settings = Settings()
