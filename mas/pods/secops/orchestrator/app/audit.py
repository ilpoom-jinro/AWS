"""
SecOps 감사 로그 싱크 (교체형) — R&R E2E의 마지막 칸 "감사로그 저장"
====================================================================
RAG retriever와 같은 패턴: "어디에 저장하느냐"를 인터페이스 뒤로 숨긴다.

구현 3개 (같은 인터페이스):
    - SqliteAuditSink  : 로컬 SQLite. RDS(PostgreSQL JSONB)와 유사 — payload를 JSON
                         컬럼에 저장하고 조회 가능. → 발표 시연용(발표자 PC, 비용 0).
    - JsonlAuditSink   : append-only JSONL. tail/cat로 바로 보이는 가장 단순한 형태.
    - SharedSdkAuditSink : shared SDK의 save_audit_log()를 그대로 호출 = 진짜 RDS 저장.
                           (구현은 이미 민수님이 해둠. 살아있는 RDS + DATABASE_URL 필요.)

교체 방법 (env):
    기본 = SQLite(로컬).  실제 RDS로 = AUDIT_SINK=shared  (+ DATABASE_URL, RDS 인스턴스)
    파일 위치는 AUDIT_DIR (기본 ./audit_logs)

주의: record_audit_log Activity 안에서만 호출됨 → Temporal 경계 밖, I/O 자유.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from contracts.models import AuditLog

AUDIT_DIR = Path(os.getenv("AUDIT_DIR", "audit_logs"))


class AuditSink(Protocol):
    async def save(self, log: AuditLog) -> None: ...


def _row(log: AuditLog) -> dict:
    """AuditLog → dict. occurred_at은 ISO 문자열로."""
    d = log.model_dump()
    oc = d.get("occurred_at")
    if isinstance(oc, datetime):
        d["occurred_at"] = oc.isoformat()
    d["payload"] = d.get("payload") or {}
    return d


# =====================================================================
# 로컬 SQLite (RDS PostgreSQL JSONB와 유사 — 발표 시연용)
# =====================================================================
class SqliteAuditSink:
    def __init__(self, path: Path | None = None) -> None:
        self._path = str(path or (AUDIT_DIR / "secops_audit.db"))
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id      TEXT NOT NULL,
                    scenario         TEXT,
                    event_type       TEXT,
                    occurred_at      TEXT,
                    actor            TEXT,
                    summary          TEXT,
                    payload          TEXT,   -- JSON (RDS의 JSONB 대응)
                    contract_version TEXT
                )
                """
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5)

    async def save(self, log: AuditLog) -> None:
        d = _row(log)
        with self._conn() as c:
            c.execute(
                "INSERT INTO audit_log "
                "(workflow_id, scenario, event_type, occurred_at, actor, summary, payload, contract_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    d.get("workflow_id"), d.get("scenario"), d.get("event_type"),
                    d.get("occurred_at"), d.get("actor"), d.get("summary"),
                    json.dumps(d["payload"], ensure_ascii=False), d.get("contract_version"),
                ),
            )


# =====================================================================
# 로컬 JSONL (가장 단순 — tail/cat)
# =====================================================================
class JsonlAuditSink:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (AUDIT_DIR / "secops_audit.jsonl")
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def save(self, log: AuditLog) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_row(log), ensure_ascii=False) + "\n")


# =====================================================================
# 실제 RDS 경로 — shared SDK (이미 구현됨). DATABASE_URL + 살아있는 RDS 필요.
# =====================================================================
class SharedSdkAuditSink:
    async def save(self, log: AuditLog) -> None:
        from shared import save_audit_log  # lazy: RDS 준비된 환경에서만 import/호출
        await save_audit_log(log)


# =====================================================================
# 팩토리 — env로 백엔드 선택 ("실제 RDS로 = AUDIT_SINK=shared")
# =====================================================================
@lru_cache(maxsize=1)
def get_audit_sink() -> AuditSink:
    kind = os.getenv("AUDIT_SINK", "sqlite").lower()
    if kind == "shared":
        return SharedSdkAuditSink()
    if kind == "jsonl":
        return JsonlAuditSink()
    return SqliteAuditSink()


# =====================================================================
# 조회 (발표 시연용 — SQLite 감사 추적 출력)
# =====================================================================
def read_audit_trail(workflow_id: str | None = None) -> list[dict]:
    db = AUDIT_DIR / "secops_audit.db"
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    try:
        if workflow_id:
            cur = con.execute(
                "SELECT * FROM audit_log WHERE workflow_id=? ORDER BY id", (workflow_id,)
            )
        else:
            cur = con.execute("SELECT * FROM audit_log ORDER BY id")
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()
