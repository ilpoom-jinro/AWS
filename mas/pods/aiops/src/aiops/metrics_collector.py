"""
metrics_collector.py — Thanos Query 메트릭 수집 (읽기 전용)

[MAS 권한 경계] 읽기 전용. 클러스터 변경 없음.
Thanos Query(observability 네임스페이스)는 Prometheus 호환 API를 제공하며,
ops/service 양쪽 클러스터 메트릭이 cluster 레이블로 구분되어 모여 있다.

detect_incident가 IncidentContext의 메트릭 필드
(cpu_usage_current, memory_usage_current, error_rate)를 채우는 데 사용한다.
모든 값은 0.0~1.0 비율(contracts 제약).
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class MetricsCollector:
    def __init__(self, thanos_url: str, timeout: int = 10) -> None:
        # e.g. http://observability-thanos-query.observability.svc.cluster.local:9090
        self.base_url = thanos_url.rstrip("/")
        self.timeout = timeout

    async def _query(self, promql: str) -> float | None:
        """instant 쿼리 → 첫 결과 스칼라 반환. 실패 시 None."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/query",
                    params={"query": promql},
                )
                resp.raise_for_status()
                result = resp.json().get("data", {}).get("result", [])
                if result:
                    return float(result[0]["value"][1])
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            logger.warning("Thanos 쿼리 실패: %s (%s)", promql, exc)
        return None

    async def collect_pod_metrics(
        self, cluster: str, namespace: str, pod: str
    ) -> dict[str, float]:
        """파드의 CPU/메모리 사용률·에러율을 0.0~1.0 비율로 반환.

        cluster 레이블로 ops/service 양쪽 클러스터를 구분한다.
        조회 실패한 지표는 0.0으로 채운다 (RCA가 메트릭 부재를 인지).
        """
        sel = f'cluster="{cluster}",namespace="{namespace}",pod="{pod}"'

        # CPU 사용률: 컨테이너 CPU 사용량 / 컨테이너 CPU limit (0~1)
        cpu = await self._query(
            f'sum(rate(container_cpu_usage_seconds_total{{{sel}}}[5m]))'
            f' / sum(kube_pod_container_resource_limits{{{sel},resource="cpu"}})'
        )
        # CPU limit 메트릭이 없으면(ksm 부재) working set 기반 대체 불가 →
        # 노드 대비 사용률로 폴백
        if cpu is None:
            cpu = await self._query(
                f'sum(rate(container_cpu_usage_seconds_total{{{sel}}}[5m]))'
            )

        # 메모리 사용률: working set / limit (0~1)
        mem = await self._query(
            f'sum(container_memory_working_set_bytes{{{sel}}})'
            f' / sum(kube_pod_container_resource_limits{{{sel},resource="memory"}})'
        )
        if mem is None:
            mem = await self._query(
                f'sum(container_memory_working_set_bytes{{{sel}}})'
                f' / sum(container_spec_memory_limit_bytes{{{sel}}} > 0)'
            )

        # 에러율: HTTP 5xx 비율 (Istio 메트릭이 있으면 활용, 없으면 0)
        err = await self._query(
            f'sum(rate(istio_requests_total{{{sel},response_code=~"5.."}}[5m]))'
            f' / sum(rate(istio_requests_total{{{sel}}}[5m]))'
        )

        def _clamp(v: float | None) -> float:
            if v is None:
                return 0.0
            return max(0.0, min(1.0, v))

        return {
            "cpu_usage_current": _clamp(cpu),
            "memory_usage_current": _clamp(mem),
            "error_rate": _clamp(err),
        }
