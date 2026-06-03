from typing import Any

from kubernetes import client, config


class KubernetesClient:
    def __init__(self) -> None:
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

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
                "ready": self._pod_ready(pod),
                "restart_count": sum(
                    status.restart_count or 0
                    for status in (pod.status.container_statuses or [])
                ),
                "containers": [
                    {
                        "name": status.name,
                        "ready": status.ready,
                        "restart_count": status.restart_count,
                        "state": self._container_state(status),
                    }
                    for status in (pod.status.container_statuses or [])
                ],
            }
            for pod in pods.items
        ]

    def list_deployments(self, namespace: str) -> list[dict[str, Any]]:
        deployments = self.apps_v1.list_namespaced_deployment(namespace=namespace)
        return [
            {
                "name": deployment.metadata.name,
                "replicas": deployment.status.replicas or 0,
                "ready_replicas": deployment.status.ready_replicas or 0,
                "available_replicas": deployment.status.available_replicas or 0,
                "updated_replicas": deployment.status.updated_replicas or 0,
                "conditions": [
                    {
                        "type": condition.type,
                        "status": condition.status,
                        "reason": condition.reason,
                        "message": condition.message,
                    }
                    for condition in (deployment.status.conditions or [])
                ],
            }
            for deployment in deployments.items
        ]

    def list_services(self, namespace: str) -> list[dict[str, Any]]:
        services = self.core_v1.list_namespaced_service(namespace=namespace)
        return [
            {
                "name": service.metadata.name,
                "type": service.spec.type,
                "cluster_ip": service.spec.cluster_ip,
                "ports": [
                    {
                        "name": port.name,
                        "port": port.port,
                        "target_port": str(port.target_port),
                    }
                    for port in (service.spec.ports or [])
                ],
            }
            for service in services.items
        ]

    def list_recent_events(self, namespace: str, limit: int = 20) -> list[dict[str, Any]]:
        events = self.core_v1.list_namespaced_event(namespace=namespace)
        sorted_events = sorted(
            events.items,
            key=lambda event: event.last_timestamp or event.event_time or event.metadata.creation_timestamp,
            reverse=True,
        )
        return [
            {
                "type": event.type,
                "reason": event.reason,
                "message": event.message,
                "involved_object": {
                    "kind": event.involved_object.kind,
                    "name": event.involved_object.name,
                },
                "last_timestamp": str(event.last_timestamp or event.event_time or event.metadata.creation_timestamp),
            }
            for event in sorted_events[:limit]
        ]

    def namespace_snapshot(self, namespace: str) -> dict[str, Any]:
        return {
            "pods": self.list_pods(namespace),
            "deployments": self.list_deployments(namespace),
            "services": self.list_services(namespace),
            "recent_events": self.list_recent_events(namespace),
        }

    def _pod_ready(self, pod: Any) -> bool:
        return any(
            condition.type == "Ready" and condition.status == "True"
            for condition in (pod.status.conditions or [])
        )

    def _container_state(self, status: Any) -> str:
        state = status.state
        if state.waiting:
            return f"waiting:{state.waiting.reason}"
        if state.terminated:
            return f"terminated:{state.terminated.reason}"
        if state.running:
            return "running"
        return "unknown"
