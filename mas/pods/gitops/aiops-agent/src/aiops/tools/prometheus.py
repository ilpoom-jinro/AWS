"""
tools/prometheus.py — Prometheus HTTP API 래퍼
VPC2 내부 Prometheus 서버(ClusterIP)에 HTTP 쿼리를 보내
메트릭 데이터를 수집한다.
"""
from __future__ import annotations

from typing import Any

import httpx


class PrometheusClient:
    def __init__(self, base_url: str, timeout: int = 15) -> None:
        # e.g. "http://prometheus-server.monitoring.svc.cluster.local:80"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── 단건 instant 쿼리 ────────────────────────────────────────

    async def query(self, promql: str) -> list[dict[str, Any]]:
        """Prometheus instant query (/api/v1/query)"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql},
            )
            resp.raise_for_status()
            data = resp.json()
        return data.get("data", {}).get("result", [])

    # ── range 쿼리 (여러 메트릭 병렬) ───────────────────────────

    async def query_range(
        self,
        queries: list[str],
        duration: str = "5m",
        step: str = "15s",
    ) -> list[dict[str, Any]]:
        """여러 PromQL을 병렬로 조회해 결과를 합쳐서 반환"""
        import asyncio

        end_ts = _now_unix()
        start_ts = end_ts - _duration_to_sec(duration)

        async def _single(promql: str) -> list[dict[str, Any]]:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/query_range",
                    params={
                        "query": promql,
                        "start": start_ts,
                        "end": end_ts,
                        "step": step,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            return data.get("data", {}).get("result", [])

        results = await asyncio.gather(*[_single(q) for q in queries], return_exceptions=True)

        merged: list[dict[str, Any]] = []
        for r in results:
            if isinstance(r, list):
                merged.extend(r)
        return merged

    # ── 장애 파드 전용 메트릭 수집 ───────────────────────────────

    async def get_pod_metrics(self, namespace: str, pod_name: str) -> dict[str, Any]:
        """특정 파드의 재시작 횟수·CPU·메모리 요약 반환"""
        queries = {
            "restarts": (
                f'kube_pod_container_status_restarts_total'
                f'{{namespace="{namespace}",pod="{pod_name}"}}'
            ),
            "cpu": (
                f'rate(container_cpu_usage_seconds_total'
                f'{{namespace="{namespace}",pod="{pod_name}"}}[5m])'
            ),
            "memory_bytes": (
                f'container_memory_usage_bytes'
                f'{{namespace="{namespace}",pod="{pod_name}"}}'
            ),
        }
        result: dict[str, Any] = {}
        for key, promql in queries.items():
            rows = await self.query(promql)
            if rows:
                result[key] = rows[0].get("value", [None, "0"])[1]
            else:
                result[key] = "N/A"
        return result


def _now_unix() -> int:
    import time
    return int(time.time())


def _duration_to_sec(duration: str) -> int:
    """'5m' → 300, '1h' → 3600"""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return int(duration[:-1]) * units.get(duration[-1], 1)
