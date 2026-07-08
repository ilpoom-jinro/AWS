"""
save_audit_log() 구현 및 DB 연결 관리

설계 결정:
    SQLAlchemy 공식 문서에서도 engine 자체를 매번 생성하지 말고 재사용할 것을 권장
    SQLAlchemy 2.x async + asyncpg 드라이버 사용
    AsyncEngine은 process-global Singleton (event loop 종속)
    첫 호출 시점에 engine 초기화 (lazy init)
    contracts.models.AuditLog → model_dump() → Core insert() → RDS
    ORM 인스턴스 생성 없이 Core insert() 사용 (오버헤드 최소화)

AuditLog.model_dump() 결과 필드:
    contract_version  ← ContractVersionMixin
    workflow_id       ← WorkflowDerivedMixin
    scenario, event_type, occurred_at, actor, summary, payload ← AuditLog

    AuditLogTable 컬럼과 1:1 대응이므로 model_dump() 그대로 삽입 가능

운영 주의:
    AsyncEngine은 생성된 event loop에 종속
    Temporal Worker 재시작 또는 테스트 환경 또는 특수한 loop lifecycle에서 유용
    pool_pre_ping=True: 네트워크 단절 후 재연결 자동 처리
"""

from __future__ import annotations

import logging

from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contracts.models import AuditLog
from shared.audit.models import AuditLogTable
from shared.config import get_settings
from shared.exceptions import AuditLogError

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
                # pydantic v2 PostgresDsn은 str 하위 타입이 아니므로 반드시 str()로 변환.
                # (원본을 그대로 넘기면 SQLAlchemy가 "Expected string or URL object, got PostgresDsn" ArgumentError)
                str(settings.database_url),
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout,
                pool_recycle=settings.db_pool_recycle,
                pool_pre_ping=settings.db_pool_pre_ping,
                echo=False,
            )
        except Exception as e:
            raise AuditLogError(f"DB 엔진 생성 실패: {e}") from e

        logger.info(
            "audit_engine_initialized",
            extra={
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
            },
        )

    return _engine


# 공개 API 

async def save_audit_log(audit_log: AuditLog) -> None:
    """
    contracts.models.AuditLog를 RDS PostgreSQL에 저장
    """

    engine = _get_engine()

    try:
        row = audit_log.model_dump()

        async with engine.begin() as conn:
            await conn.execute(
                insert(AuditLogTable).values(**row)
            )

        logger.info(
            "audit_log_saved",
            extra={
                "workflow_id": audit_log.workflow_id,
                "scenario": audit_log.scenario,
                "event_type": audit_log.event_type,
                "actor": audit_log.actor,
            },
        )

    except SQLAlchemyError as e:
        logger.error(
            "audit_log_save_failed",
            extra={
                "workflow_id": audit_log.workflow_id,
                "event_type": audit_log.event_type,
                "error": str(e),
            },
        )

        raise AuditLogError(
            f"AuditLog INSERT 실패 "
            f"[workflow_id={audit_log.workflow_id}, "
            f"event_type={audit_log.event_type}]: {e}"
        ) from e

    except Exception as e:
        logger.error(
            "audit_log_unexpected_error",
            extra={
                "workflow_id": audit_log.workflow_id,
                "event_type": audit_log.event_type,
                "error": str(e),
            },
        )

        raise AuditLogError(
            f"AuditLog 저장 중 예상치 못한 오류 "
            f"[workflow_id={audit_log.workflow_id}, "
            f"event_type={audit_log.event_type}]: {e}"
        ) from e


# 내부 유틸 

async def _reset_engine() -> None:
    """
    Engine 강제 초기화

    호출 시점:
        Temporal Worker 재시작
        event loop 교체
        테스트 격리

    Example:
        await _reset_engine()
    """
    global _engine

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("audit_engine_disposed")