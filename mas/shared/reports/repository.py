"""
save_compliance_report() 구현

설계 결정:
    SQLAlchemy 2.x async + asyncpg. DB 엔진은 shared/db/engine.py의 공통 싱글톤을
    사용한다(audit/reports/postmortem/monthly 공유 — 엔진 보일러플레이트 통합).
    contracts.models.ComplianceReport → model_dump() → Core insert() → RDS
    ORM 인스턴스 생성 없이 Core insert() 사용 (오버헤드 최소화)

ComplianceReport.model_dump() 결과 필드:
    contract_version  ← ContractVersionMixin
    workflow_id       ← WorkflowDerivedMixin
    generated_at, severity, violated_regulations, threat_summary,
    action_taken, isolation_applied, confidence, evidence ← ComplianceReport

    ComplianceReportTable 컬럼과 1:1 대응이므로 model_dump() 그대로 삽입 가능
"""

from __future__ import annotations

import logging

from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError

from contracts.models import ComplianceReport, PostMortemReport
from shared.db.engine import dispose_engine, get_engine
from shared.exceptions import ReportError
from shared.reports.models import ComplianceReportTable, PostMortemReportTable

logger = logging.getLogger(__name__)


# 공개 API

async def save_compliance_report(report: ComplianceReport) -> None:
    """
    contracts.models.ComplianceReport를 RDS PostgreSQL에 저장
    """

    try:
        engine = get_engine()
    except Exception as e:
        raise ReportError(f"DB 엔진 생성 실패: {e}") from e

    try:
        row = report.model_dump()

        async with engine.begin() as conn:
            await conn.execute(
                insert(ComplianceReportTable).values(**row)
            )

        logger.info(
            "compliance_report_saved",
            extra={
                "workflow_id": report.workflow_id,
                "severity": report.severity,
                "isolation_applied": report.isolation_applied,
            },
        )

    except SQLAlchemyError as e:
        logger.error(
            "compliance_report_save_failed",
            extra={
                "workflow_id": report.workflow_id,
                "error": str(e),
            },
        )

        raise ReportError(
            f"ComplianceReport INSERT 실패 "
            f"[workflow_id={report.workflow_id}]: {e}"
        ) from e

    except Exception as e:
        logger.error(
            "compliance_report_unexpected_error",
            extra={
                "workflow_id": report.workflow_id,
                "error": str(e),
            },
        )

        raise ReportError(
            f"ComplianceReport 저장 중 예상치 못한 오류 "
            f"[workflow_id={report.workflow_id}]: {e}"
        ) from e


async def save_postmortem_report(report: PostMortemReport) -> None:
    """
    contracts.models.PostMortemReport를 RDS PostgreSQL에 저장.
    save_compliance_report와 동일 패턴(Core insert + 공통 엔진).
    PostMortemReport.model_dump() 필드가 PostMortemReportTable 컬럼과 1:1 대응.
    """

    try:
        engine = get_engine()
    except Exception as e:
        raise ReportError(f"DB 엔진 생성 실패: {e}") from e

    try:
        row = report.model_dump()

        async with engine.begin() as conn:
            await conn.execute(
                insert(PostMortemReportTable).values(**row)
            )

        logger.info(
            "postmortem_report_saved",
            extra={
                "workflow_id": report.workflow_id,
                "severity": report.severity,
                "isolation_applied": report.isolation_applied,
            },
        )

    except SQLAlchemyError as e:
        logger.error(
            "postmortem_report_save_failed",
            extra={"workflow_id": report.workflow_id, "error": str(e)},
        )
        raise ReportError(
            f"PostMortemReport INSERT 실패 "
            f"[workflow_id={report.workflow_id}]: {e}"
        ) from e

    except Exception as e:
        logger.error(
            "postmortem_report_unexpected_error",
            extra={"workflow_id": report.workflow_id, "error": str(e)},
        )
        raise ReportError(
            f"PostMortemReport 저장 중 예상치 못한 오류 "
            f"[workflow_id={report.workflow_id}]: {e}"
        ) from e


# 내부 유틸 (하위호환) — 공통 엔진 dispose로 위임

async def _reset_engine() -> None:
    """Engine 강제 초기화. shared/db 공통 엔진 dispose로 위임."""
    await dispose_engine()
