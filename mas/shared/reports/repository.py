"""
save_compliance_report() 구현 및 DB 연결 관리

설계 결정 (shared/audit/repository.py 패턴 그대로 미러링):
    SQLAlchemy 2.x async + asyncpg 드라이버 사용
    AsyncEngine은 process-global Singleton (event loop 종속)
    첫 호출 시점에 engine 초기화 (lazy init)
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
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contracts.models import ComplianceReport
from shared.config import get_settings
from shared.exceptions import ReportError
from shared.reports.models import ComplianceReportTable

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    """
    AsyncEngine 싱글톤 반환. 첫 호출 시 생성
    """
    global _engine

    if _engine is None:
        settings = get_settings()

        try:
            _engine = create_async_engine(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout,
                pool_recycle=settings.db_pool_recycle,
                pool_pre_ping=settings.db_pool_pre_ping,
                echo=False,
            )
        except Exception as e:
            raise ReportError(f"DB 엔진 생성 실패: {e}") from e

        logger.info(
            "report_engine_initialized",
            extra={
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
            },
        )

    return _engine


# 공개 API

async def save_compliance_report(report: ComplianceReport) -> None:
    """
    contracts.models.ComplianceReport를 RDS PostgreSQL에 저장
    """

    engine = _get_engine()

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


# 내부 유틸

async def _reset_engine() -> None:
    """
    Engine 강제 초기화 (Temporal Worker 재시작 / event loop 교체 / 테스트 격리)
    """
    global _engine

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("report_engine_disposed")
