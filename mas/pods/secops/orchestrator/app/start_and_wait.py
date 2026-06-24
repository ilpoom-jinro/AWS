"""
실제 Temporal 서버(localhost:7233)에 SecOpsWorkflow를 시작하고 결과를 기다린다.

run_demo.py와의 차이:
    run_demo  = 임베디드 서버 + 자동 승인 (한 방에 끝)
    이 파일    = 실제 서버 + 자동 승인 안 함 → wait_condition에서 멈춰 외부 signal을 기다림
                (= Slack 봇이 보낼 승인을 signal_approval.py로 수동 시뮬레이션하기 위함)

전제 (다른 터미널에서 실행 중이어야 함):
    1) temporal server start-dev
    2) python -m pods.secops.orchestrator.app.worker

실행 (mas/ 에서):
    python -m pods.secops.orchestrator.app.start_and_wait
"""

from __future__ import annotations

import asyncio
import os
import uuid

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from contracts.models import DetectThreatInput
from .workflow import SecOpsWorkflow

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "secops-task-queue")


async def main() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS, data_converter=pydantic_data_converter)
    wf_id = f"secops-{uuid.uuid4().hex[:8]}"
    handle = await client.start_workflow(
        SecOpsWorkflow.run,
        args=[DetectThreatInput(cluster_name="financial-ops-eks", vpc_id="vpc-0a1b2c3d")],
        id=wf_id,
        task_queue=TASK_QUEUE,
    )
    print("workflow 시작됨 — 위반 분석 후 승인 대기 (durable). 외부 signal 기다리는 중.")
    print(f"  WORKFLOW_ID = {wf_id}")
    print(f"  다른 터미널에서:  python -m pods.secops.orchestrator.app.signal_approval {wf_id} approve")
    print("  (Temporal UI localhost:8233 에서 멈춰있는 워크플로우를 볼 수 있음)\n")

    report = await handle.result()   # signal 올 때까지 여기서 대기
    print("=== 최종 ComplianceReport ===")
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
