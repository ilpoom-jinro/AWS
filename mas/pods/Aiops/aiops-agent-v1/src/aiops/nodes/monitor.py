"""
nodes/monitor.py — MONITOR 노드

[v0.2 수정사항]
- Prometheus 조회 실패가 전체 사이클을 죽이던 문제
  → 예외 격리: Prometheus가 죽어도 파드 상태 기반 감지는 계속 동작
- Service EKS 접근 실패(kubeconfig 미구성 등) 시에도
  Ops 클러스터 단독 감시로 동작하도록 폴백
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from ..state import AgentState
from ..tools.k8s_client import K8sClient
from ..tools.prometheus import PrometheusClient

logger = logging.getLogger(__name__)

PROM_QUERIES = [
    "kube_pod_container_status_restarts_total",
    "kube_pod_container_status_last_terminated_reason",
    "rate(container_cpu_usage_seconds_total[5m])",
    "container_memory_usage_bytes",
]


async def _safe_list_pods(context: str, label: str) -> list:
    """클러스터 접근 실패 시 빈 목록 반환 (다른 클러스터 감시는 지속)"""
    try:
        k8s = K8sClient(context=context)
        return await k8s.list_pods_all_namespaces()
    except Exception as exc:
        logger.warning("%s 파드 수집 실패: %s", label, exc)
        return []


async def _safe_metrics() -> list:
    """Prometheus 실패 시 빈 메트릭 반환 (감지 자체는 파드 상태 기반으로 지속)"""
    try:
        prom = PrometheusClient(settings.PROMETHEUS_URL)
        return await prom.query_range(queries=PROM_QUERIES, duration="5m")
    except Exception as exc:
        logger.warning("Prometheus 수집 실패: %s", exc)
        return []


async def run(state: AgentState) -> AgentState:
    """MONITOR 노드 진입점"""
    pods_ops, pods_svc, metrics = await asyncio.gather(
        _safe_list_pods(settings.OPS_KUBE_CONTEXT, "Ops EKS"),
        _safe_list_pods(settings.SERVICE_KUBE_CONTEXT, "Service EKS"),
        _safe_metrics(),
    )

    logger.info(
        "수집 완료: ops=%d pods, svc=%d pods, metrics=%d series",
        len(pods_ops), len(pods_svc), len(metrics),
    )

    return {
        **state,
        "raw_metrics": metrics,
        "raw_logs": [],
        "_pods_ops": pods_ops,
        "_pods_svc": pods_svc,
        "events": [],
    }
