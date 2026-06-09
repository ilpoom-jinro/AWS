"""
nodes/monitor.py — MONITOR 노드
30초마다 VPC1(Service EKS) + VPC2(Ops EKS) 파드 상태와
Prometheus 메트릭을 수집한다.
"""
from __future__ import annotations

import asyncio

from ..config import settings
from ..state import AgentState
from ..tools.k8s_client import K8sClient
from ..tools.prometheus import PrometheusClient


async def run(state: AgentState) -> AgentState:
    """MONITOR 노드 진입점"""
    k8s_ops = K8sClient(context=settings.OPS_KUBE_CONTEXT)
    k8s_svc = K8sClient(context=settings.SERVICE_KUBE_CONTEXT)
    prom = PrometheusClient(settings.PROMETHEUS_URL)

    # 두 클러스터 파드 목록 + Prometheus 메트릭 병렬 수집
    pods_ops, pods_svc, metrics = await asyncio.gather(
        k8s_ops.list_pods_all_namespaces(),
        k8s_svc.list_pods_all_namespaces(),
        prom.query_range(
            queries=[
                "kube_pod_container_status_restarts_total",
                "kube_pod_container_status_last_terminated_reason",
                "rate(container_cpu_usage_seconds_total[5m])",
                "container_memory_usage_bytes",
            ],
            duration="5m",
        ),
    )

    return {
        **state,
        "raw_metrics": metrics,
        "raw_logs": [],          # detect 단계에서 채움
        "_pods_ops": pods_ops,
        "_pods_svc": pods_svc,
        "events": [],            # 이전 주기 이벤트 초기화
    }
