"""
SecOps Temporal Worker
======================
실제 dev 루프용. 별도로 떠 있는 Temporal 서버에 붙어서
SecOpsWorkflow와 Activity들을 등록하고 task를 처리한다 (FinOps orchestrator와 동일 구조).

실행 (mas/ 디렉터리에서):
    터미널 1) temporal server start-dev          # localhost:7233 + UI localhost:8233
    터미널 2) python -m secops_temporal.worker    # 이 워커 (AWS/Bedrock env 필요)
    터미널 3) python -m secops_temporal.run_demo   # 워크플로우 시작 + 승인 시그널

map_regulation에서 실제 Bedrock을 쓰려면 이 워커 터미널에 환경변수를 줘야 함:
    USE_REAL_BEDROCK / BEDROCK_MODEL / DATABASE_URL / AWS 자격증명(MFA 세션)
"""

from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from secops_temporal.activities import (
    apply_isolation,
    detect_threat,
    generate_compliance_report,
    map_regulation,
    record_audit_log,
    send_approval_request,
)
from secops_temporal.workflow import SecOpsWorkflow

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "secops-task-queue")


async def main() -> None:
    # Pydantic 모델을 Activity 입출력으로 쓰므로 pydantic 데이터 컨버터 필수
    client = await Client.connect(TEMPORAL_ADDRESS, data_converter=pydantic_data_converter)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[SecOpsWorkflow],
        activities=[
            detect_threat,
            map_regulation,
            apply_isolation,
            generate_compliance_report,
            send_approval_request,
            record_audit_log,
        ],
    )
    print(f"[worker] connected {TEMPORAL_ADDRESS}, task_queue={TASK_QUEUE} — waiting for tasks (Ctrl+C로 종료)")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())