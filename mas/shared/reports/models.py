"""
Compliance Report DB 모델이자 contracts.models.ComplianceReport와 1:1 매핑되는 저장용 테이블

역할 구분:
    contracts/models.py  ComplianceReport      = Pydantic   = "데이터가 어떻게 생겼는가" (Agent 간 계약)
    shared/reports/models.py ComplianceReportTable = SQLAlchemy = "RDS 테이블이 어떻게 생겼는가" (인프라 스키마)

주의:
    ComplianceReport 필드 변경 시 ComplianceReportTable도 함께 수정 필요
    ComplianceReportTable은 저장 구현체임. Agent가 직접 사용하지 않는다
    (shared/audit/models.py AuditLogTable 패턴을 그대로 미러링)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ComplianceReportTable(Base):
    __tablename__ = "compliance_reports"

    __table_args__ = (
        # workflow_id + generated_at 복합 인덱스 (감사로그 idx_audit_logs_workflow_occurred와 동일 취지)
        Index(
            "idx_compliance_reports_workflow_generated",
            "workflow_id",
            "generated_at",
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

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    violated_regulations: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
    )

    threat_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    action_taken: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    isolation_applied: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    evidence: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    blast_radius_safe: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    blast_radius_detail: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("''"),
    )


class PostMortemReportTable(Base):
    """
    Post-Mortem Report DB 모델 — contracts.models.PostMortemReport와 1:1 매핑.
    ComplianceReportTable 패턴을 그대로 미러링(Sev1/2 사후분석 저장용).
    """
    __tablename__ = "postmortem_reports"

    __table_args__ = (
        Index(
            "idx_postmortem_reports_workflow_generated",
            "workflow_id",
            "generated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False)

    contract_version: Mapped[str] = mapped_column(String(16), nullable=False)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    incident_summary: Mapped[str] = mapped_column(Text, nullable=False)

    timeline: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("''"),
    )

    root_cause: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("''"),
    )

    impact: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("''"),
    )

    action_items: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'"),
    )

    lessons_learned: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("''"),
    )

    isolation_applied: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
