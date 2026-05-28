import os
from typing import Any

import httpx


class PrometheusClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_env(cls) -> "PrometheusClient":
        return cls(os.getenv("PROMETHEUS_URL", "http://prometheus-server.monitoring.svc.cluster.local"))

    @classmethod
    def from_url(cls, base_url: str) -> "PrometheusClient":
        return cls(base_url)

    async def query(self, query: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query},
            )
            response.raise_for_status()
            return response.json()
