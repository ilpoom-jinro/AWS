"""
실제 Temporal 서버(localhost:7233)에 SecOpsWorkflow를 시작하고 결과를 기다린다.

run_demo.py와의 차이:
    run_demo  = 임베디드 서버 + 자동 승인 (한 방에 끝, 슬랙 불필요)
    이 파일    = 실제 서버 + 자동 승인 안 함 → 승인 Activity(슬랙 봇)를 거쳐 사람 결정 대기

전제 (다른 터미널에서 실행 중이어야 함):
    1) temporal server start-dev
    2) python -m pods.secops.orchestrator.app.worker     ← SecOps 워커
    3) python slack-hitl/bot.py                           ← 슬랙 봇 (HITL 큐 + Socket Mode)

흐름: 이 스크립트가 워크플로우 시작 → 봇이 슬랙에 승인 메시지 게시 →
      사람이 슬랙에서 '✅ 승인' 클릭 → 봇이 submit_approval 시그널 전송 → 여기서 결과 출력.
      (봇 없이 수동으로 깨우려면 signal_approval.py 사용 — 단, 그땐 봇 대신 HITL 큐 스텁 워커 필요)

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