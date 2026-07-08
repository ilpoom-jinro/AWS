"""
공통 async DB 엔진 (audit/reports/postmortem/monthly 리포지토리 공유)

설계:
    SQLAlchemy 2.x async + asyncpg. AsyncEngine은 process-global Singleton
    (event loop 종속) — 첫 호출 시 lazy init.
    기존 shared/audit·shared/reports가 동일한 엔진 보일러플레이트를 복붙하던 것을
    한 곳으로 통합. 각 save_* 리포지토리는 get_engine()만 사용한다.
    (엔진 설정은 shared.config.get_settings() 단일 소스라 도메인별 차이 없음)
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from shared.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """AsyncEngine 싱글톤 반환. 첫 호출 시 생성."""
    global _engine

    if _engine is None:
        settings = get_settings()

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

        logger.info(
            "db_engine_initialized",
            extra={
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
            },
        )

    return _engine


async def dispose_engine() -> None:
    """Engine 강제 초기화 (Temporal Worker 재시작 / event loop 교체 / 테스트 격리)."""
    global _engine

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("db_engine_disposed")
