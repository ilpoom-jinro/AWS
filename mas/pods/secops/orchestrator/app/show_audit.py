"""
감사 로그 조회 CLI (RDS/PostgreSQL) — 발표에서 감사 추적 표시.

실행 (mas/ 에서, DATABASE_URL 설정 후):
    python -m pods.secops.orchestrator.app.show_audit                 # 전체
    python -m pods.secops.orchestrator.app.show_audit <WORKFLOW_ID>   # 특정 워크플로우
"""

from __future__ import annotations

import sys

from .audit import read_audit_trail


def main() -> None:
    wf = sys.argv[1] if len(sys.argv) > 1 else None
    rows = read_audit_trail(wf)
    if not rows:
        print("감사 로그 없음 (audit_logs 비어있음 또는 DATABASE_URL 확인)")
        return
    title = f"({wf})" if wf else "(전체)"
    print(f"=== 감사 로그 {title} — {len(rows)}건 ===")
    for r in rows:
        print(f"[{r['occurred_at']}] {str(r['event_type']):<20} "
              f"{str(r['actor']):<16} {r['summary']}  payload={r['payload']}")


if __name__ == "__main__":
    main()
