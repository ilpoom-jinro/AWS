"""
AIOps Temporal Worker
=====================
두 파일에서 Activities를 분리 import한다:
  activities_platform.py — Platform Core 소유 (execute_remediation, execute_rollback, record_audit_log)
  activities_aiops.py    — AIOps 팀 소유 (detect_incident, analyze_root_cause, verify_recovery)

AIOps 팀이 자신의 Activity를 교체해도 Platform Core 코드는 영향받지 않는다.

실행 (mas/ 에서):
    python -m pods.aiops.orchestrator.app.worker

필요 환경변수:
    TEMPORAL_ADDRESS    (기본 localhost:7233)
    TEMPORAL_TASK_QUEUE (기본 aiops-task-queue)
    DATABASE_URL        postgresql+asyncpg://user:pass@host:5432/dbname
"""

from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from .activities_aiops import analyze_root_cause, detect_incident, verify_recovery
from .activities_platform import execute_remediation, execute_rollback, record_audit_log
from .workflow import AIOpsRemediationWorkflow

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "aiops-task-queue")


async def main() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS, data_converter=pydantic_data_converter)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AIOpsRemediationWorkflow],
        activities=[
            # AIOps 팀 소유 — v1.3.0 구현체 교체 대상
            detect_incident,
            analyze_root_cause,
            verify_recovery,
            # Platform Core 소유 — 수정 금지
            execute_remediation,
            execute_rollback,
            record_audit_log,
        ],
        # 주의: send_approval_request / send_reminder 는 여기 없음 —
        #       slack-hitl/bot.py가 HITL_TASK_QUEUE에서 단독 소유.
    )

    print(
        f"[aiops-worker] connected {TEMPORAL_ADDRESS}, "
        f"task_queue={TASK_QUEUE} — waiting for tasks (Ctrl+C로 종료)"
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
