"""
worker.py — Temporal Worker 진입점

v0.3의 main.py(FastAPI + 자체 루프)를 대체한다.
LangGraph 자체 루프와 Slack WebHook은 제거되었다 (MAS 일원화).

이 Worker는 AIOps Activity 3종(detect/analyze/verify)과
AIOpsRemediationWorkflow를 등록한다.
execute_remediation/rollback/request_approval/record_audit_log는
다른 Worker(Platform Core / Common)가 등록하므로 여기 없음.
"""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import aiops_activities
from .config import settings
from .workflow import AIOpsRemediationWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    client = await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
    )
    logger.info(
        "AIOps Worker 시작 (queue=%s, temporal=%s)",
        settings.TEMPORAL_TASK_QUEUE,
        settings.TEMPORAL_HOST,
    )

    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[AIOpsRemediationWorkflow],
        activities=[
            aiops_activities.detect_incident,
            aiops_activities.analyze_root_cause,
            aiops_activities.verify_recovery,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
