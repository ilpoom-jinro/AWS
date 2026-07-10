"""
api.py — SecOps orchestrator HTTP API (UI/헬스체크용)
=====================================================
순수 Temporal 워커였던 SecOps에 HTTP API를 얹는다(AIOps trigger.py 패턴).
worker.py/poller와 함께 run.py에서 uvicorn으로 병행 실행된다.

엔드포인트:
    GET  /health                     — 배포 프로브용
    POST /api/workflows/run          — 탐지 워크플로 수동 실행 (발표 시연: trigger_message 없으면 더미 탐지)
    GET  /api/workflows/{id}         — 워크플로 상태/결과 조회
    GET  /api/reports                — 저장된 규제 보고서 목록 (RDS)
    GET  /api/audit-logs             — 감사 로그 (RDS)
    GET  /api/dashboard              — 대시보드 요약 + 최근 보고서/로그

필요 env: TEMPORAL_ADDRESS, TEMPORAL_TASK_QUEUE (worker.py와 동일), DATABASE_URL(조회)
"""

from __future__ import annotations

import logging
import os
import uuid

from fastapi import FastAPI, HTTPException, Query
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter

from contracts.models import DetectThreatInput

from . import queries
from .workflow import SecOpsWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("secops.api")

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "secops-task-queue")
CLUSTER_NAME = os.getenv("SECOPS_CLUSTER_NAME", "financial-ops-eks")
VPC_ID = os.getenv("SECOPS_VPC_ID", "vpc-ops")

app = FastAPI(title="SecOps API", version="1.0.0")

_client: Client | None = None


async def _get_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(TEMPORAL_ADDRESS, data_converter=pydantic_data_converter)
    return _client


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/workflows/run")
async def run_workflow(trigger_message: str = "") -> dict:
    """
    탐지 워크플로 수동 실행. trigger_message가 있으면 그 메시지를 파싱,
    없으면 detect_threat가 더미 이벤트를 생성한다(발표 시연용).
    """
    client = await _get_client()
    wf_id = f"secops-ui-{uuid.uuid4().hex[:12]}"
    await client.start_workflow(
        SecOpsWorkflow.run,
        DetectThreatInput(cluster_name=CLUSTER_NAME, vpc_id=VPC_ID, trigger_message=trigger_message),
        id=wf_id,
        task_queue=TASK_QUEUE,
    )
    logger.info("워크플로 시작(UI): %s", wf_id)
    return {"workflow_id": wf_id, "status": "started"}


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict:
    """워크플로 상태 조회. 완료됐으면 ComplianceReport 결과 포함."""
    client = await _get_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        desc = await handle.describe()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"workflow not found: {exc}") from exc

    status = desc.status.name if desc.status else "UNKNOWN"
    result = None
    if desc.status == WorkflowExecutionStatus.COMPLETED:
        try:
            report = await handle.result()
            result = report.model_dump(mode="json") if hasattr(report, "model_dump") else report
        except Exception as exc:  # noqa: BLE001
            logger.warning("결과 조회 실패 %s: %s", workflow_id, exc)
    return {"workflow_id": workflow_id, "status": status, "result": result}


@app.get("/api/reports")
def get_reports(limit: int = Query(50, ge=1, le=200), workflow_id: str | None = None) -> dict:
    try:
        return {"reports": queries.list_compliance_reports(limit=limit, workflow_id=workflow_id)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"DB 조회 실패: {exc}") from exc


@app.get("/api/audit-logs")
def get_audit_logs(limit: int = Query(100, ge=1, le=500), workflow_id: str | None = None) -> dict:
    try:
        return {"audit_logs": queries.list_audit_logs(limit=limit, workflow_id=workflow_id)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"DB 조회 실패: {exc}") from exc


@app.get("/api/dashboard")
def dashboard() -> dict:
    """대시보드 초기 로드용 — 요약 + 최근 보고서/로그 한 번에."""
    try:
        return {
            "summary": queries.compliance_summary(),
            "recent_reports": queries.list_compliance_reports(limit=10),
            "recent_audit_logs": queries.list_audit_logs(limit=20),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"DB 조회 실패: {exc}") from exc
