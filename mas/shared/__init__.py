"""
Shared SDK 퍼블릭 API

현재 SDK가 제공하는 기능:
  get_bedrock_client() — Bedrock Runtime Client 생성
  ClaudeModel - claude 모델 ID 표준화
  save_audit_log()     — AuditLog → RDS PostgreSQL 저장

주의:
- Agent(FinOps / AIOps / SecOps)는 shared 패키지만 import 하기
- 내부 구현체(bedrock/, audit/)는 SDK 내부 세부사항임
"""

from shared.audit import save_audit_log
from shared.bedrock import ClaudeModel, get_bedrock_client
from shared.exceptions import (
    AuditLogError,
    BedrockClientError,
    ConfigurationError,
    SDKError,
)

__all__ = [
    # 핵심 API
    "get_bedrock_client",
    "save_audit_log",

    # 클로드 모델
    "ClaudeModel",

    # 예외 처리 
    "SDKError",
    "BedrockClientError",
    "AuditLogError",
    "ConfigurationError",
]