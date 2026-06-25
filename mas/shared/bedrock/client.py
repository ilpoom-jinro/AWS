"""
Bedrock 공통 클라이언트.

모든 Agent는 이 client.py를 통해 Bedrock에 접근한다
boto3 직접 호출 금지 — 반드시 get_bedrock_client() 사용

설계 원칙:
    - AWS IRSA Credential Chain 사용
    - boto3 Session 직접 생성 금지
    - Bedrock Runtime Client Singleton 재사용
    - SDK 레이어는 Retry 수행하지 않음
    - Retry는 Temporal RetryPolicy가 담당

에러 처리 규칙:
    - ThrottlingException → 그대로 raise
    - ValidationException → Activity에서 non_retryable 처리
    - BedrockClientError → Client 생성 실패

Example:
    from shared.bedrock import get_bedrock_client, ClaudeModel

    client = get_bedrock_client()

    response = client.converse(
        modelId=ClaudeModel.SONNET,
        messages=[
            {
                "role": "user",
                "content": [{"text": "분석해줘"}],
            }
        ],
    )
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from functools import lru_cache

import boto3
import botocore.client
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from shared.exceptions import BedrockClientError

logger = logging.getLogger(__name__)


class ClaudeModel(str, Enum):
    HAIKU = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    SONNET = "global.anthropic.claude-sonnet-4-6"
    OPUS = "global.anthropic.claude-opus-4-6-v1"


_BOTO_CONFIG = Config(
    connect_timeout=10,
    read_timeout=30,
    retries={
        "max_attempts": 0,
    },  # Retry는 Temporal이 담당
)


@lru_cache(maxsize=1)
def get_bedrock_client() -> botocore.client.BaseClient:
    """
    Bedrock Runtime Client 반환.

    Returns:
        boto3 Bedrock Runtime Client

    Raises:
        BedrockClientError:
            - Credential 획득 실패
            - Region 설정 오류
            - Client 생성 실패
    """
    region = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION", "ap-northeast-2")

    try:
        client = boto3.client(
            service_name="bedrock-runtime",
            region_name=region,
            config=_BOTO_CONFIG,
        )

    except (BotoCoreError, ClientError) as e:
        raise BedrockClientError(
            f"Bedrock 클라이언트 생성에 실패했습니다: {e}"
        ) from e

    logger.info(
        "bedrock_client_created",
        extra={
            "region": region,
        },
    )

    return client
