"""
SecOps Temporal — 제로 셋업 데모
================================
Temporal CLI 설치도, 별도 서버/워커 터미널도 필요 없음.
이 스크립트 하나가:
    1) 임베디드 dev 서버를 띄우고 (start_local; 최초 1회 바이너리 자동 다운로드)
    2) 워커를 in-process로 등록하고
    3) SecOpsWorkflow를 시작한 뒤
    4) "사람이 Slack에서 승인" 하는 걸 시뮬레이션해 signal을 보내고
    5) 최종 ComplianceReport를 출력한다.

실행 (mas/ 디렉터리에서):
    pip install temporalio
    python -m secops_temporal.run_demo

    # map_regulation에 실제 Claude를 태우려면 (선택):
    #   $env:USE_REAL_BEDROCK="true"; $env:BEDROCK_MODEL="global.anthropic.claude-haiku-4-5-20251001-v1:0"
    #   $env:DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/dummy"  + MFA 세션 자격증명

실제 dev 루프(서버/워커 분리)는 secops_temporal/worker.py 참고.
"""

from __future__ import annotations

import asyncio
import uuid

from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from contracts.models import DetectThreatInput
from secops_temporal.activities import (
    apply_isolation,
    detect_threat,
    generate_compliance_report,
    map_regulation,
    record_audit_log,
    send_approval_request,
)
from secops_temporal.workflow import SecOpsWorkflow

TASK_QUEUE = "secops-task-queue"


async def main() -> None:
    print("[demo] 임베디드 Temporal dev 서버 시작 중... (최초 실행 시 바이너리 다운로드)")
    async with await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
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
        ):
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


if __name__ == "__main__":
    asyncio.run(main())