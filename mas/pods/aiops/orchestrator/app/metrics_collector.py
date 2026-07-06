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

    async def _query_vector(self, promql: str) -> list[tuple[dict, float]]:
        """instant 쿼리 → (labels, value) 리스트 반환. 실패 시 빈 리스트.

        여러 시계열(예: 파드별 P95)을 한 번에 받을 때 사용한다.
        """
        out: list[tuple[dict, float]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/query",
                    params={"query": promql},
                )
                resp.raise_for_status()
                for series in resp.json().get("data", {}).get("result", []):
                    try:
                        out.append((series.get("metric", {}), float(series["value"][1])))
                    except (KeyError, ValueError, IndexError):
                        continue
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("Thanos vector 쿼리 실패: %s (%s)", promql, exc)
        return out

    async def find_high_latency_pod(
        self, cluster: str, namespace: str, threshold_ms: float
    ) -> tuple[str, float] | None:
        """네임스페이스에서 Istio P95 요청 지연이 임계값(ms)을 넘는 최악의 파드 반환.

        반환: (pod_name, p95_ms) — 임계값 초과 파드 중 가장 느린 1건. 없으면 None.
        error_rate 쿼리와 동일한 Istio telemetry(istio_request_duration_milliseconds) 계열 사용.
        NaN/임계값 이하는 제외. Thanos 미응답 시 빈 결과 → None (탐지 스킵, 사이클 유지).
        """
        promql = (
            "histogram_quantile(0.95, sum by (pod, le) (rate("
            f'istio_request_duration_milliseconds_bucket{{cluster="{cluster}",'
            f'namespace="{namespace}"}}[5m])))'
        )
        worst_pod: str | None = None
        worst_val = threshold_ms
        for labels, value in await self._query_vector(promql):
            pod = labels.get("pod", "")
            # value != value → NaN 제외 (지연 데이터 없는 파드)
            if not pod or value != value:
                continue
            if value > worst_val:
                worst_pod, worst_val = pod, value
        if worst_pod is not None:
            return worst_pod, worst_val
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
        # kube-state-metrics가 일시적으로 없을 때를 대비한 폴백:
        # cadvisor가 제공하는 spec 기반 limit(quota/period = 코어 수)으로 나눠
        # 0~1 비율을 유지한다. (절대 사용량만 반환하면 비율이 깨지므로 금지)
        if cpu is None:
            cpu = await self._query(
                f'sum(rate(container_cpu_usage_seconds_total{{{sel}}}[5m]))'
                f' / sum(container_spec_cpu_quota{{{sel}}} / container_spec_cpu_period{{{sel}}})'
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
