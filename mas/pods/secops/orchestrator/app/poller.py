"""
SecOps 트리거 SQS Poller
========================
financial-secops-trigger SQS 큐(봉근님 secops-trigger.tf)를 폴링해, 메시지가 오면
그 원본을 DetectThreatInput.trigger_message에 실어 SecOpsWorkflow를 기동한다.
워크플로 기동 성공 시에만 메시지 삭제(실패 시 재수신 → DLQ).

env:
    SECOPS_TRIGGER_QUEUE_URL  트리거 큐 URL (configmap 주입)
    SECOPS_CLUSTER_NAME       cluster_name (기본 financial-ops-eks)
    SECOPS_VPC_ID             vpc_id (기본 vpc2/ops)
    AWS_REGION
격리 ops VPC에서 SQS 도달은 SQS VPC 엔드포인트 경유(vpc/ops/endpoints.tf).
"""

from __future__ import annotations

import asyncio
import os
import uuid

from temporalio.client import Client

from contracts.models import DetectThreatInput
from .workflow import SecOpsWorkflow

QUEUE_URL = os.getenv("SECOPS_TRIGGER_QUEUE_URL", "")
CLUSTER_NAME = os.getenv("SECOPS_CLUSTER_NAME", "financial-ops-eks")
VPC_ID = os.getenv("SECOPS_VPC_ID", "vpc-ops")
REGION = os.getenv("AWS_REGION", "ap-northeast-2")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "secops-task-queue")


async def _start_workflow(client: Client, body: str) -> str:
    wf_id = f"secops-{uuid.uuid4().hex[:12]}"
    await client.start_workflow(
        SecOpsWorkflow.run,
        args=[DetectThreatInput(cluster_name=CLUSTER_NAME, vpc_id=VPC_ID, trigger_message=body)],
        id=wf_id,
        task_queue=TASK_QUEUE,
    )
    return wf_id


async def poll_loop(client: Client) -> None:
    """SQS 롱폴링 루프. 메시지→워크플로 기동→삭제. (blocking boto3는 스레드로)"""
    if not QUEUE_URL:
        print("[poller] SECOPS_TRIGGER_QUEUE_URL 미설정 — poller 비활성")
        return

    import boto3

    sqs = boto3.client("sqs", region_name=REGION)
    print(f"[poller] polling {QUEUE_URL}")
    while True:
        resp = await asyncio.to_thread(
            sqs.receive_message,
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,   # 롱폴링
            VisibilityTimeout=300,
        )
        for msg in resp.get("Messages", []):
            body, receipt = msg["Body"], msg["ReceiptHandle"]
            try:
                wf_id = await _start_workflow(client, body)
                print(f"[poller] workflow started: {wf_id}")
                # 기동 성공 → 메시지 삭제
                await asyncio.to_thread(
                    sqs.delete_message, QueueUrl=QUEUE_URL, ReceiptHandle=receipt
                )
            except Exception as exc:  # noqa: BLE001  기동 실패 → 삭제 안 함(재수신→DLQ)
                print(f"[poller] start failed, will retry via SQS: {exc}")
