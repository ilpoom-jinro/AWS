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
import asyncio
import time

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from contracts.models import DetectIncidentInput

from .config import settings
from .k8s_collector import K8sCollector
from .nodes.detector import EXCLUDED_NAMESPACES, _detect_reason
from .workflow import AIOpsRemediationWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aiops.trigger")

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "aiops-task-queue")
MONITORED_CLUSTERS = (
    "financial-ops-eks",
    "financial-service-eks",
)
POD_SUMMARY_CACHE_TTL_SECONDS = 3.0

app = FastAPI(title="AIOps Alert Trigger", version="1.3.0")

_client: Client | None = None
_pod_summary_cache: dict[str, tuple[float, dict[str, object]]] = {}
_pod_summary_locks = {cluster: asyncio.Lock() for cluster in MONITORED_CLUSTERS}


class RunWorkflowRequest(BaseModel):
    cluster_name: str
    namespace: str
    workflow_id: str | None = None


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
    - 조치 제외 namespace는 모니터링 전용으로 남기고 Workflow를 시작하지 않는다.
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
        if cluster and namespace and namespace not in EXCLUDED_NAMESPACES:
            targets.add((cluster, namespace))
        elif cluster and namespace:
            logger.info(
                "조치 제외 namespace 알림은 모니터링 전용으로 처리: %s/%s",
                cluster, namespace,
            )
        else:
            logger.warning(
                "cluster/namespace label 없는 alert 건너뜀: %s",
                labels.get("alertname", "unknown"),
            )
    return targets


def _context_for_cluster(cluster_name: str) -> str:
    """cluster_name에 맞는 K8sCollector context를 반환한다."""
    if cluster_name == settings.SERVICE_EKS_CLUSTER_NAME:
        return settings.SERVICE_KUBE_CONTEXT
    return settings.OPS_KUBE_CONTEXT


def _is_ready_pod(pod: dict) -> bool:
    """Running이며 모든 컨테이너가 Ready인 Pod만 정상으로 집계한다."""
    status = pod.get("status", {})
    if status.get("phase") != "Running":
        return False
    containers = status.get("container_statuses") or status.get("containerStatuses") or []
    return bool(containers) and all(container.get("ready", False) for container in containers)


async def _collect_pod_summary(cluster_name: str) -> dict[str, object]:
    """클러스터 Pod를 조치 가능 장애와 모니터링 전용 경보로 분리 집계한다."""
    collector = K8sCollector(context=_context_for_cluster(cluster_name))
    pods = await collector.list_pods_all_namespaces()
    namespaces: set[str] = set()
    actionable_problem_namespaces: set[str] = set()
    monitoring_problem_namespaces: set[str] = set()
    normal_pod_count = 0
    actionable_problem_pod_count = 0
    monitoring_problem_pod_count = 0
    other_pod_count = 0

    for pod in pods:
        namespace = pod.get("metadata", {}).get("namespace", "")
        if namespace:
            namespaces.add(namespace)

        if _detect_reason(pod):
            if namespace in EXCLUDED_NAMESPACES:
                monitoring_problem_pod_count += 1
                if namespace:
                    monitoring_problem_namespaces.add(namespace)
            else:
                actionable_problem_pod_count += 1
                if namespace:
                    actionable_problem_namespaces.add(namespace)
        elif _is_ready_pod(pod):
            normal_pod_count += 1
        else:
            other_pod_count += 1

    return {
        "cluster_name": cluster_name,
        "namespace_names": sorted(namespaces),
        "actionable_namespace_names": sorted(
            namespace for namespace in namespaces if namespace not in EXCLUDED_NAMESPACES
        ),
        "monitoring_namespace_names": sorted(
            namespace for namespace in namespaces if namespace in EXCLUDED_NAMESPACES
        ),
        "normal_pod_count": normal_pod_count,
        # 기존 UI 호환용 problem_*은 실제 조치 가능한 장애만 뜻한다.
        "problem_pod_count": actionable_problem_pod_count,
        "other_pod_count": other_pod_count,
        "problem_namespaces": sorted(actionable_problem_namespaces),
        "monitoring_problem_pod_count": monitoring_problem_pod_count,
        "monitoring_problem_namespaces": sorted(monitoring_problem_namespaces),
    }


async def _cached_pod_summary(cluster_name: str) -> dict[str, object]:
    """3초 TTL로 원격 Service EKS API와 Ops API의 중복 조회를 줄인다."""
    if cluster_name not in _pod_summary_locks:
        raise ValueError(f"지원하지 않는 클러스터: {cluster_name}")

    now = time.monotonic()
    cached = _pod_summary_cache.get(cluster_name)
    if cached and now - cached[0] < POD_SUMMARY_CACHE_TTL_SECONDS:
        return cached[1]

    async with _pod_summary_locks[cluster_name]:
        cached = _pod_summary_cache.get(cluster_name)
        if cached and time.monotonic() - cached[0] < POD_SUMMARY_CACHE_TTL_SECONDS:
            return cached[1]
        summary = await _collect_pod_summary(cluster_name)
        _pod_summary_cache[cluster_name] = (time.monotonic(), summary)
        return summary


async def _dashboard_cluster_summary(cluster_name: str) -> dict[str, object]:
    try:
        return await _cached_pod_summary(cluster_name)
    except Exception as exc:
        logger.exception("Pod 상태 집계 실패: %s", cluster_name)
        return {
            "cluster_name": cluster_name,
            "namespace_names": [],
            "actionable_namespace_names": [],
            "monitoring_namespace_names": [],
            "normal_pod_count": 0,
            "problem_pod_count": 0,
            "other_pod_count": 0,
            "problem_namespaces": [],
            "monitoring_problem_pod_count": 0,
            "monitoring_problem_namespaces": [],
            "error": str(exc),
        }


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


@app.get("/api/dashboard")
async def dashboard() -> dict[str, object]:
    cluster_summaries = await asyncio.gather(
        *(_dashboard_cluster_summary(cluster) for cluster in MONITORED_CLUSTERS)
    )
    return {
        "scenario": "aiops",
        "agent": "orchestrator",
        "task_queue": TASK_QUEUE,
        "temporal_address": TEMPORAL_ADDRESS,
        "targets": [
            {"cluster_name": "financial-ops-eks", "namespace": "tetragon"},
            {"cluster_name": "financial-service-eks", "namespace": "stock-demo"},
        ],
        "cluster_summaries": cluster_summaries,
    }


@app.get("/api/clusters/{cluster_name}/namespaces")
async def cluster_namespaces(cluster_name: str) -> dict[str, object]:
    """수동 AIOps 조치가 가능한 namespace 목록을 반환한다."""
    summary = await _cached_pod_summary(cluster_name)
    return {
        "cluster_name": cluster_name,
        "namespaces": summary["actionable_namespace_names"],
        "monitoring_only_namespaces": summary["monitoring_namespace_names"],
    }


@app.get("/api/workflows/{workflow_id}")
async def workflow_detail(workflow_id: str) -> dict[str, object]:
    """Temporal workflow 상태와 완료된 경우 result를 조회한다."""
    client = await _get_client()
    handle = client.get_workflow_handle(workflow_id)
    description = await handle.describe()
    status = getattr(description.status, "name", str(description.status))

    response: dict[str, object] = {
        "workflow_id": workflow_id,
        "status": status,
        "result": None,
    }
    try:
        response["result"] = await asyncio.wait_for(handle.result(), timeout=0.2)
    except asyncio.TimeoutError:
        response["result"] = None
    except Exception as exc:
        response["status"] = "FAILED"
        response["result"] = str(exc)
    return response


@app.post("/api/workflows/run")
async def run_workflow(request: RunWorkflowRequest) -> dict[str, str]:
    """UI/API에서 수동으로 AIOps remediation workflow를 시작한다."""
    if request.namespace in EXCLUDED_NAMESPACES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{request.namespace}은(는) 운영 시스템 모니터링 전용 namespace입니다. "
                "AIOps 자동 조치 대상이 아닙니다."
            ),
        )
    client = await _get_client()
    wf_id = request.workflow_id or (
        f"aiops-{request.cluster_name}-{request.namespace}-manual-{uuid.uuid4().hex[:8]}"
    )
    await client.start_workflow(
        AIOpsRemediationWorkflow.run,
        DetectIncidentInput(
            cluster_name=request.cluster_name,
            namespace=request.namespace,
        ),
        id=wf_id,
        task_queue=TASK_QUEUE,
    )
    logger.info(
        "수동 워크플로 시작: %s (%s/%s)",
        wf_id,
        request.cluster_name,
        request.namespace,
    )
    return {
        "workflow_id": wf_id,
        "cluster_name": request.cluster_name,
        "namespace": request.namespace,
        "task_queue": TASK_QUEUE,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
