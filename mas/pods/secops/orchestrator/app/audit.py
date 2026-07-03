"""
SecOps 감사 로그 조회 (RDS/PostgreSQL) — 발표에서 "감사 추적이 이렇게 쌓입니다" 표시용.

저장(write)은 activities.record_audit_log → shared.audit.repository.save_audit_log 가
RDS 전용으로 담당한다. 이 모듈은 그 audit_logs 테이블을 읽기(read)만 한다.

DATABASE_URL 필요: postgresql+asyncpg://user:pass@host:5432/dbname
  - 저장은 asyncpg(비동기), 조회는 동기 psycopg 사용 → +asyncpg 접미사는 자동 제거
로컬 발표: deploy/local/docker-compose.yml 의 Postgres를 띄우고 DATABASE_URL을 거기로.
"""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL 미설정 (예: postgresql+asyncpg://mas:mas@localhost:5432/mas)"
        )
    return url.replace("+asyncpg", "")   # 동기 psycopg는 순수 postgresql:// URL 사용


def read_audit_trail(workflow_id: str | None = None) -> list[dict]:
    """audit_logs 조회. workflow_id 지정 시 해당 워크플로우만, 아니면 전체."""
    cols = "occurred_at, event_type, actor, summary, payload"
    with psycopg.connect(_dsn()) as conn, conn.cursor(row_factory=dict_row) as cur:
        if workflow_id:
            cur.execute(
                f"SELECT {cols} FROM audit_logs WHERE workflow_id = %s ORDER BY occurred_at",
                (workflow_id,),
            )
        else:
            cur.execute(f"SELECT {cols} FROM audit_logs ORDER BY occurred_at")
        return cur.fetchall()
