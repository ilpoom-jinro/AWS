"""
k8s_collector.py — 읽기 전용 K8s 수집 도구

[MAS 권한 경계] Agent는 실행 권한이 없다 (activity_interfaces.py 명시).
따라서 이 모듈은 조회(list/read)만 제공하며, rollout restart/undo/scale 같은
변경 명령은 제공하지 않는다. 실제 실행은 Platform Core Activity가 담당한다.

멀티 클러스터: entrypoint가 생성한 /tmp/kubeconfig의 컨텍스트별로
독립 ApiClient를 만든다 (v0.3 구조 유지).
"""
from __future__ import annotations

import asyncio
from typing import Any

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException


def _make_api_client(context: str) -> client.ApiClient:
    """in-cluster 설정 우선, 실패 시 kubeconfig context 폴백.

    EKS Pod 내부: load_incluster_config() 성공 → ServiceAccount 토큰 사용.
    로컬 개발:    ConfigException → new_client_from_config(context=context) 폴백.
    """
    try:
        k8s_config.load_incluster_config()
        return client.ApiClient()
    except k8s_config.ConfigException:
        return k8s_config.new_client_from_config(context=context)


class K8sCollector:
    """컨텍스트별 읽기 전용 Kubernetes 수집기"""

    def __init__(self, context: str) -> None:
        self.context = context
        api_client = _make_api_client(context)
        self._core = client.CoreV1Api(api_client)
        self._apps = client.AppsV1Api(api_client)

    async def list_pods_all_namespaces(self) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: self._core.list_pod_for_all_namespaces(watch=False)
        )
        pods = []
        for item in resp.items:
            d = item.to_dict()
            pods.append(d)
        return pods

    async def list_namespace_pods(self, namespace: str) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: self._core.list_namespaced_pod(namespace, watch=False)
        )
        return [item.to_dict() for item in resp.items]

    async def get_pod_logs(
        self, namespace: str, pod_name: str, tail: int = 50, previous: bool = False
    ) -> str:
        """파드 로그 tail 줄 반환.

        [MAS] recent_logs는 contracts에서 max_length=50으로 제한되므로
        기본 tail을 50으로 둔다 (Temporal payload 2MB 대응).
        CrashLoop는 현재 컨테이너 로그가 비어 previous 폴백이 필요할 수 있다.
        """
        loop = asyncio.get_event_loop()
        try:
            logs = await loop.run_in_executor(
                None,
                lambda: self._core.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=tail,
                    previous=previous,
                    _preload_content=True,
                ),
            )
            return logs or ""
        except ApiException as exc:
            if not previous and exc.status == 400:
                # 현재 컨테이너 로그 없음 → previous 폴백
                return await self.get_pod_logs(namespace, pod_name, tail, previous=True)
            return f"[로그 조회 실패: {exc.status} {exc.reason}]"

    async def get_pod_events(self, namespace: str, pod_name: str) -> list[str]:
        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(
                None,
                lambda: self._core.list_namespaced_event(
                    namespace=namespace,
                    field_selector=f"involvedObject.name={pod_name}",
                ),
            )
            return [f"{e.reason}: {e.message}" for e in resp.items]
        except ApiException:
            return []
