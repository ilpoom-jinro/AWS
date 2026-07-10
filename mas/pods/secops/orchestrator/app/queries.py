"""
RDS 조회 헬퍼 (UI/API용)
========================
SecOps 워크플로 결과는 RDS에 저장된다:
    - compliance_reports (규제 보고서)   ← shared/reports
    - audit_logs         (감사 로그)     ← shared/audit
UI/API가 이 테이블들을 읽어 화면에 뿌린다. 저장은 비동기(asyncpg)지만
조회는 동기 psycopg를 쓴다(audit.py와 동일 패턴, +asyncpg 접미사 자동 제거).
"""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL 미설정")
    return url.replace("+asyncpg", "")


def list_compliance_reports(limit: int = 50, workflow_id: str | None = None) -> list[dict]:
    """규제 보고서 목록 (최신순)."""
    cols = ("workflow_id, contract_version, generated_at, severity, "
            "violated_regulations, threat_summary, action_taken, "
            "isolation_applied, confidence, evidence")
    with psycopg.connect(_dsn()) as conn, conn.cursor(row_factory=dict_row) as cur:
        if workflow_id:
            cur.execute(
                f"SELECT {cols} FROM compliance_reports WHERE workflow_id = %s "
                "ORDER BY generated_at DESC",
                (workflow_id,),
            )
        else:
            cur.execute(
                f"SELECT {cols} FROM compliance_reports ORDER BY generated_at DESC LIMIT %s",
                (limit,),
            )
        return cur.fetchall()


def list_audit_logs(limit: int = 100, workflow_id: str | None = None) -> list[dict]:
    """감사 로그 목록 (최신순)."""
    cols = "workflow_id, scenario, event_type, occurred_at, actor, summary, payload"
    with psycopg.connect(_dsn()) as conn, conn.cursor(row_factory=dict_row) as cur:
        if workflow_id:
            cur.execute(
                f"SELECT {cols} FROM audit_logs WHERE workflow_id = %s ORDER BY occurred_at",
                (workflow_id,),
            )
        else:
            cur.execute(
                f"SELECT {cols} FROM audit_logs ORDER BY occurred_at DESC LIMIT %s",
                (limit,),
            )
        return cur.fetchall()


def compliance_summary() -> dict:
    """대시보드 상단 요약: 보고서 수, severity 분포, 격리 적용률, 감사로그 수."""
    with psycopg.connect(_dsn()) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM compliance_reports")
        total_reports = cur.fetchone()["n"]
        cur.execute("SELECT severity, COUNT(*) AS n FROM compliance_reports GROUP BY severity")
        by_severity = {r["severity"]: r["n"] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) AS n FROM compliance_reports WHERE isolation_applied = true")
        isolated = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM audit_logs")
        total_audit = cur.fetchone()["n"]
    return {
        "total_reports": total_reports,
        "by_severity": by_severity,
        "isolation_applied": isolated,
        "total_audit_logs": total_audit,
    }
