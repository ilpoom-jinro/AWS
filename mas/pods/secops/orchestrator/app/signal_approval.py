"""
승인/거부 signal 수동 전송기 — Slack HITL 봇의 동작을 시뮬레이션한다.

핵심:
    이 스크립트가 하는 일이 곧 슬랙 봇(mas/slack-hitl/bot.py, 민수님 영역)이
    "승인/거부 버튼 클릭" 시 해야 할 일과 똑같다.
    → 그래서 이 파일은 민수님과의 연동 계약서 역할도 한다.

봇이 추가로 해야 할 일 (이 스크립트엔 없는 부분):
    - send_approval_request 시점에 Slack 메시지를 올리고,
      그 메시지에 "어떤 워크플로우인지"(=아래 WORKFLOW_ID)를 버튼 value/metadata로 심어두기
    - 버튼 클릭 이벤트가 오면 그 value에서 WORKFLOW_ID를 꺼내 아래처럼 signal

전제: temporal server start-dev + worker 실행 중, start_and_wait로 워크플로우가 대기 중.

실행 (mas/ 에서):
    python -m pods.secops.orchestrator.app.signal_approval <WORKFLOW_ID> approve|reject [reviewer_id]
"""

from __future__ import annotations

import asyncio
import os
import sys

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from .workflow import SecOpsWorkflow

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")


async def main() -> None:
    if len(sys.argv) < 3 or sys.argv[2] not in ("approve", "reject"):
        print("usage: python -m pods.secops.orchestrator.app.signal_approval <WORKFLOW_ID> approve|reject [reviewer_id]")
        raise SystemExit(1)

    wf_id = sys.argv[1]
    approved = sys.argv[2] == "approve"
    reviewer = sys.argv[3] if len(sys.argv) > 3 else "sre-oncall"

    client = await Client.connect(TEMPORAL_ADDRESS, data_converter=pydantic_data_converter)
    handle = client.get_workflow_handle(wf_id)

    # ▼▼▼ 슬랙 봇이 버튼 클릭 시 실행해야 할 바로 그 호출 ▼▼▼
    await handle.signal(
        SecOpsWorkflow.submit_approval,
        args=[approved, reviewer, "manual signal (slack bot simulation)"],
    )
    # ▲▲▲ 이 한 줄이 SecOps↔Slack-HITL 연동의 핵심 계약 ▲▲▲

    print(f"signal 전송 완료 → workflow={wf_id}, approved={approved}, reviewer={reviewer}")


if __name__ == "__main__":
    asyncio.run(main())
