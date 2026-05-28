from typing import Any

from kubernetes import client, config


class KubernetesClient:
    def __init__(self) -> None:
        self.core_v1 = client.CoreV1Api()

    @classmethod
    def from_cluster(cls) -> "KubernetesClient":
        config.load_incluster_config()
        return cls()

    def list_pods(self, namespace: str) -> list[dict[str, Any]]:
        pods = self.core_v1.list_namespaced_pod(namespace=namespace)
        return [
            {
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "node": pod.spec.node_name,
            }
            for pod in pods.items
        ]
