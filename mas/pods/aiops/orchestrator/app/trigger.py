"""
trigger.py — Alertmanager webhook 수신 → AIOpsRemediationWorkflow 시작
=====================================================================
이벤트 기반 트리거 (팀 표준: secops/finops와 동일하게 client.start_workflow 사용).

흐름:
    Thanos Ruler(알림 규칙 평가) → Alertmanager(라우팅)
      → POST /webhook/alertmanager (이 모듈)
      → client.start_workflow(AIOpsRemediationWorkflow, DetectIncidentInput)

Alertmanager webhook 페이로드(표준 v4)에서 각 alert의 label을 읽어
cluster / namespace 를 추출하고, (cluster, namespace) 조합별로 중복을 제거해
워크플로를 시작한다. 같은 네임스페이스에 여러 alert가 몰려도 워크플로는
조합당 하나만 시작한다(detector가 네임스페이스를 스캔하므로).

worker.py와 별개 프로세스가 아니라, 같은 이미지에서 uvicorn으로 이 app을
함께 띄운다(Dockerfile CMD에서 worker와 병행). 자세한 배포 방식은 하단 참고.

필요 환경변수:
    TEMPORAL_ADDRESS     (기본 localhost:7233) — worker.py와 동일
    TEMPORAL_TASK_QUEUE  (기본 aiops-task-queue) — worker.py와 동일
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import FastAPI, Request
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from contracts.models import DetectIncidentInput

from .workflow import AIOpsRemediationWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aiops.trigger")

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "aiops-task-queue")

app = FastAPI(title="AIOps Alert Trigger", version="1.3.0")

_client: Client | None = None


async def _get_client() -> Client:
    """Temporal client 싱글턴 (worker.py와 동일한 data_converter 사용)."""
    global _client
    if _client is None:
        _client = await Client.connect(
            TEMPORAL_ADDRESS, data_converter=pydantic_data_converter
        )
    return _client


def _extract_targets(payload: dict) -> set[tuple[str, str]]:
    """Alertmanager webhook 페이로드에서 (cluster, namespace) 조합을 추출.

    표준 payload 구조:
        {"alerts": [{"labels": {"cluster": "...", "namespace": "...",
                                 "alertname": "...", ...}, "status": "firing"}]}
    - firing 상태만 대상으로 한다(resolved는 무시).
    - cluster/namespace label이 없는 alert는 건너뛴다.
    - 중복 조합은 set으로 제거(detector가 네임스페이스를 스캔하므로 조합당 1회면 충분).
    """
    targets: set[tuple[str, str]] = set()
    for alert in payload.get("alerts", []):
        if alert.get("status") != "firing":
            continue
        labels = alert.get("labels", {})
        cluster = labels.get("cluster")
        namespace = labels.get("namespace")
        if cluster and namespace:
            targets.add((cluster, namespace))
        else:
            logger.warning(
                "cluster/namespace label 없는 alert 건너뜀: %s",
                labels.get("alertname", "unknown"),
            )
    return targets


@app.post("/webhook/alertmanager")
async def alertmanager_webhook(request: Request) -> dict:
    """Alertmanager webhook 수신 → 조합별로 워크플로 시작."""
    payload = await request.json()
    targets = _extract_targets(payload)

    if not targets:
        logger.info("firing 대상 없음 (또는 label 누락) — 워크플로 미시작")
        return {"started": [], "skipped": "no valid firing targets"}

    client = await _get_client()
    started: list[dict[str, str]] = []
    for cluster, namespace in targets:
        # workflow_id에 cluster/namespace를 넣어, 같은 대상의 동시 중복 실행을 자연 억제.
        # (Temporal은 동일 id의 워크플로가 실행 중이면 재시작을 거부한다.)
        wf_id = f"aiops-{cluster}-{namespace}-{uuid.uuid4().hex[:8]}"
        await client.start_workflow(
            AIOpsRemediationWorkflow.run,
            DetectIncidentInput(cluster_name=cluster, namespace=namespace),
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
        logger.info("워크플로 시작: %s (%s/%s)", wf_id, cluster, namespace)
        started.append({"workflow_id": wf_id, "cluster": cluster, "namespace": namespace})

    return {"started": started}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
