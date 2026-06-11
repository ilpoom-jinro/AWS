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
    # [v0.3] 모니터링 스택 전환 반영 (Prometheus 단일 서버 → Thanos 스택):
    # - Alloy가 kubelet/cadvisor/annotated-pods만 스크랩하고 kube-state-metrics가
    #   없으므로 kube_pod_* 시리즈는 존재하지 않아 제거.
    #   (파드 상태 탐지는 detector.py가 K8s API를 직접 조회하므로 영향 없음)
    # - cadvisor 제공 메트릭으로 CPU/메모리 추이를 RCA 보조 자료로 수집.
    # - Thanos Query 한 곳에서 ops/service 양쪽 클러스터 메트릭 조회 가능
    #   (Alloy remote_write external_labels: cluster=<클러스터명>)
    "rate(container_cpu_usage_seconds_total[5m])",
    "container_memory_usage_bytes",
    "container_memory_working_set_bytes",
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
