"""
Audit Log DB 모델이자 contracts.models.AuditLog와 1:1 매핑되는 저장용 테이블

역할 구분:
    contracts/models.py  AuditLog       = Pydantic   = "데이터가 어떻게 생겼는가" (Agent 간 계약)
    shared/audit/models.py AuditLogTable = SQLAlchemy = "RDS 테이블이 어떻게 생겼는가" (인프라 스키마)


주의:
    AuditLog 필드 변경 시 AuditLogTable도 함께 수정 필요
    AuditLogTable은 저장 구현체임. Agent가 직접 사용하지 않는다
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, JSONB, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AuditLogTable(Base):
    __tablename__ = "audit_logs"

    __table_args__ = (
        # workflow_id 단일 인덱스 제거 — 복합 인덱스가 단일 컬럼 조회도 커버
        # 만약 "FinOps 시나리오 전체 로그" 또는 "특정 actor가 발생시킨 이벤트 전체" 
        # 같은 Audit Log 조회 UI/대시보드 요구사항이 나오면 그때 인덱스 추가할 것
        Index(
            "idx_audit_logs_workflow_occurred",
            "workflow_id",
            "occurred_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    workflow_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    contract_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    scenario: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    actor: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    # Text: contracts.models.AuditLog의 summary는 길이 제한 없음
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )