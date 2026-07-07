"""
SecOps Temporal Worker
======================
실제 dev 루프용. 별도로 떠 있는 Temporal 서버에 붙어서
SecOpsWorkflow와 Activity들을 등록하고 task를 처리한다 (FinOps orchestrator와 동일 구조).

실행 (mas/ 디렉터리에서):
    터미널 1) temporal server start-dev          # localhost:7233 + UI localhost:8233
    터미널 2) python -m pods.secops.orchestrator.app.worker    # 이 워커 (AWS/Bedrock env 필요)
    터미널 3) python -m pods.secops.orchestrator.app.run_demo   # 워크플로우 시작 + 승인 시그널

map_regulation에서 실제 Bedrock을 쓰려면 이 워커 터미널에 환경변수를 줘야 함:
    USE_REAL_BEDROCK / BEDROCK_MODEL / DATABASE_URL / AWS 자격증명(MFA 세션)
"""

from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from .activities import (
    apply_isolation,
    detect_threat,
    generate_compliance_report,
    map_regulation,
    record_audit_log,
    record_compliance_report,
)
from .workflow import SecOpsWorkflow

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
            record_compliance_report,
            record_audit_log,
        ],
        # 주의: send_approval_request / send_reminder 는 여기 없음 —
        #       공통 슬랙 봇(pods/platform/slack-hitl/bot.py)이 전용 큐(HITL_TASK_QUEUE)에서 소유.
    )
    print(f"[worker] connected {TEMPORAL_ADDRESS}, task_queue={TASK_QUEUE} — waiting for tasks (Ctrl+C로 종료)")
    # 워커 + SQS poller 동시 실행 (poller는 트리거 큐를 폴링해 워크플로 기동)
    from .poller import poll_loop
    async with worker:
        await poll_loop(client)


if __name__ == "__main__":
    asyncio.run(main())
