"""
SecOps Temporal — 로컬 데모 (Temporal은 임베디드, 감사 로그는 RDS/Postgres)
========================================================================
Temporal 서버 터미널은 필요 없지만(임베디드 dev 서버), 감사 로그가 RDS 전용이라
발표자 PC에 로컬 Postgres 1개가 필요하다.

이 스크립트 하나가:
    1) 임베디드 Temporal dev 서버를 띄우고 (start_local; 최초 1회 바이너리 자동 다운로드)
    2) 워커를 in-process로 등록하고
    3) SecOpsWorkflow를 시작한 뒤
    4) "사람이 Slack에서 승인" 하는 걸 시뮬레이션해 signal을 보내고
    5) 최종 ComplianceReport + 저장된 감사 로그(Postgres)를 출력한다.

사전 준비 (감사 로그 저장/조회용 로컬 Postgres):
    cd mas/deploy/local && docker compose up -d
    $env:DATABASE_URL="postgresql+asyncpg://mas:mas@localhost:5432/mas"

실행 (mas/ 에서):
    pip install temporalio sqlalchemy asyncpg "psycopg[binary]"
    python -m pods.secops.orchestrator.app.run_demo

    # map_regulation에 실제 Claude를 태우려면 (선택):
    #   $env:USE_REAL_BEDROCK="true"; $env:BEDROCK_MODEL="global.anthropic.claude-haiku-4-5-20251001-v1:0"
    #   + MFA 세션 자격증명
"""

from __future__ import annotations

import asyncio
import os
import uuid

from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from contracts.models import DetectThreatInput
from .activities import (
    apply_isolation,
    detect_threat,
    generate_compliance_report,
    map_regulation,
    record_audit_log,
    send_approval_request,
)
from .workflow import HITL_TASK_QUEUE, SecOpsWorkflow

TASK_QUEUE = "secops-task-queue"


async def main() -> None:
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL 미설정 — 감사 로그가 RDS 전용이라 로컬 Postgres가 필요합니다.\n"
              "  1) cd mas/deploy/local && docker compose up -d\n"
              '  2) $env:DATABASE_URL="postgresql+asyncpg://mas:mas@localhost:5432/mas"')
        return
    print("[demo] 임베디드 Temporal dev 서버 시작 중... (최초 실행 시 바이너리 다운로드)")
    async with await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter) as env:
        # SecOps 워커(워크플로우 + 에이전트 Activity)
        secops_worker = Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SecOpsWorkflow],
            activities=[
                detect_threat,
                map_regulation,
                apply_isolation,
                generate_compliance_report,
                record_audit_log,
            ],
        )
        # 승인 큐 워커 — 실제 봇 대신 스텁 send_approval_request (슬랙 없이 데모 완주용)
        hitl_stub_worker = Worker(
            env.client,
            task_queue=HITL_TASK_QUEUE,
            activities=[send_approval_request],
        )
        async with secops_worker, hitl_stub_worker:
            wf_id = f"secops-{uuid.uuid4().hex[:8]}"
            handle = await env.client.start_workflow(
                SecOpsWorkflow.run,
                args=[DetectThreatInput(cluster_name="financial-ops-eks", vpc_id="vpc-0a1b2c3d")],
                id=wf_id,
                task_queue=TASK_QUEUE,
            )
            print(f"[demo] workflow {wf_id} 시작 → 위반 분석 후 사람 승인 대기")

            # 사람이 Slack에서 검토하는 시간 시뮬레이션
            await asyncio.sleep(1)
            await handle.signal(
                SecOpsWorkflow.submit_approval,
                args=[True, "sre-oncall", "확인된 악성 outbound — 격리 승인"],
            )
            print("[demo] 승인 signal 전송 → 워크플로우 재개 (apply_isolation 실행)")

            report = await handle.result()
            print("\n=== 최종 ComplianceReport ===")
            print(report.model_dump_json(indent=2))

            # R&R E2E의 마지막 칸: 저장된 감사 로그 출력 ("...감사로그 저장까지")
            from .audit import read_audit_trail
            trail = read_audit_trail(report.workflow_id)
            print(f"\n=== 감사 로그 (workflow={report.workflow_id}) — {len(trail)}건 저장됨 ===")
            for r in trail:
                print(f"  [{r['occurred_at']}] {r['event_type']:<20} {r['actor']:<16} {r['summary']}")


if __name__ == "__main__":
    asyncio.run(main())
