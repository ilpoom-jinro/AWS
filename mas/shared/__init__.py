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

from shared.exceptions import (
    AuditLogError,
    BedrockClientError,
    ConfigurationError,
    ReportError,
    SDKError,
)


def __getattr__(name: str):
    if name == "save_audit_log":
        from shared.audit import save_audit_log

        return save_audit_log
    if name == "save_compliance_report":
        from shared.reports import save_compliance_report

        return save_compliance_report
    if name in {"ClaudeModel", "get_bedrock_client"}:
        from shared.bedrock import ClaudeModel, get_bedrock_client

        return {
            "ClaudeModel": ClaudeModel,
            "get_bedrock_client": get_bedrock_client,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # 핵심 API
    "get_bedrock_client",
    "save_audit_log",
    "save_compliance_report",

    # 클로드 모델
    "ClaudeModel",

    # 예외 처리 
    "SDKError",
    "BedrockClientError",
    "AuditLogError",
    "ReportError",
    "ConfigurationError",
]
