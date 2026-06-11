"""
tools/k8s_client.py — kubectl / kubernetes SDK 래퍼

[v0.2 수정사항]
- 기존: load_incluster_config() 사용 시 context 파라미터가 무시되어
  K8sClient("service-context")도 로컬(Ops) 클러스터만 바라봄.
  또한 CoreV1Api()가 전역 설정을 공유해 마지막에 로드된 설정으로 덮어써짐.
- 수정: entrypoint.sh가 생성한 kubeconfig(/tmp/kubeconfig)에서
  new_client_from_config(context=...)로 컨텍스트별 독립 ApiClient 생성.
  kubeconfig가 없으면 in-cluster로 폴백(단일 클러스터 모드).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)

KUBECONFIG_PATH = os.environ.get("KUBECONFIG", "/tmp/kubeconfig")


class K8sClient:
    """컨텍스트별 독립 Kubernetes API 클라이언트"""

    def __init__(self, context: str) -> None:
        self.context = context
        api_client = self._build_api_client(context)
        self._core = client.CoreV1Api(api_client)
        self._apps = client.AppsV1Api(api_client)

    @staticmethod
    def _build_api_client(context: str) -> client.ApiClient:
        """kubeconfig 파일 기반 컨텍스트별 ApiClient. 없으면 in-cluster 폴백."""
        if os.path.exists(KUBECONFIG_PATH):
            try:
                return k8s_config.new_client_from_config(
                    config_file=KUBECONFIG_PATH, context=context
                )
            except Exception as exc:
                logger.warning(
                    "kubeconfig 컨텍스트 '%s' 로드 실패(%s) — in-cluster 폴백", context, exc
                )
        # in-cluster 폴백: 로컬(Ops) 클러스터 전용
        k8s_config.load_incluster_config()
        return client.ApiClient()

    # ── 파드 조회 ─────────────────────────────────────────────────

    async def list_pods_all_namespaces(self) -> list[dict[str, Any]]:
        """전체 네임스페이스 파드 목록을 dict 리스트로 반환"""
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: self._core.list_pod_for_all_namespaces(watch=False),
        )
        pods = []
        for item in resp.items:
            pod_dict = item.to_dict()
            pods.append(pod_dict)
        return pods

    async def get_pod_logs(
        self, namespace: str, pod_name: str, tail: int = 200
    ) -> str:
        """파드 로그 tail 줄 반환. 실패 시 사유 문자열 반환."""
        loop = asyncio.get_event_loop()
        try:
            logs = await loop.run_in_executor(
                None,
                lambda: self._core.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=tail,
                    previous=False,
                    _preload_content=True,
                ),
            )
            return logs or ""
        except ApiException as exc:
            # CrashLoop 파드는 현재 컨테이너 로그가 없을 수 있음 → 직전 컨테이너 로그 시도
            try:
                logs = await loop.run_in_executor(
                    None,
                    lambda: self._core.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        tail_lines=tail,
                        previous=True,
                        _preload_content=True,
                    ),
                )
                return f"[직전 컨테이너 로그]\n{logs or ''}"
            except ApiException:
                return f"[로그 조회 실패: {exc.status} {exc.reason}]"

    async def get_pod_events(self, namespace: str, pod_name: str) -> list[str]:
        """파드 관련 K8s 이벤트 반환"""
        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(
                None,
                lambda: self._core.list_namespaced_event(
                    namespace=namespace,
                    field_selector=f"involvedObject.name={pod_name}",
                ),
            )
            return [
                f"{e.reason}: {e.message} (count={e.count})"
                for e in resp.items
            ]
        except ApiException:
            return []


async def _run_cmd(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    """
    비동기 subprocess 실행, (returncode, output) 반환.
    KUBECONFIG 환경변수는 프로세스 환경에서 자동 상속된다.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode if proc.returncode is not None else -1, stdout.decode(errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        return -1, f"[타임아웃: {timeout}초 초과]"
