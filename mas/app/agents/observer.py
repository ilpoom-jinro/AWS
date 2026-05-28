from typing import Any

from app.tools.kubernetes import KubernetesClient
from app.tools.prometheus import PrometheusClient


class ObserverAgent:
    def __init__(self, prometheus: PrometheusClient, kubernetes: KubernetesClient | None = None) -> None:
        self.prometheus = prometheus
        self.kubernetes = kubernetes

    async def collect_namespace_signals(self, namespace: str) -> dict[str, Any]:
        restarts_query = (
            "sum(increase(kube_pod_container_status_restarts_total"
            f'{{namespace="{namespace}"}}[15m])) by (pod)'
        )
        signals: dict[str, Any] = {
            "pod_restarts_15m": {
                "query": restarts_query,
                "result": await self.prometheus.query(restarts_query),
            }
        }

        if self.kubernetes:
            signals["pods"] = self.kubernetes.list_pods(namespace)

        return signals
