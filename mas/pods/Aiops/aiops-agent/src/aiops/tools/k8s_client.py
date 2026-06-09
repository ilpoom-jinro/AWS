"""
tools/k8s_client.py — kubectl 래퍼
kubernetes Python SDK를 사용해 파드 목록/로그/이벤트 조회 및
rollout restart / scale / rollout undo 실행을 추상화한다.
"""
from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException


class K8sClient:
    """컨텍스트별 Kubernetes API 클라이언트"""

    def __init__(self, context: str) -> None:
        self.context = context
        # kubeconfig 로드 (파드 내부 → in-cluster, 로컬 → ~/.kube/config)
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config(context=context)

        self._core = client.CoreV1Api()
        self._apps = client.AppsV1Api()
        self._autoscaling = client.AutoscalingV1Api()

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
            pod_dict["_vpc"] = "vpc2" if "ops" in self.context else "vpc1"
            pods.append(pod_dict)
        return pods

    async def get_pod_logs(
        self, namespace: str, pod_name: str, tail: int = 200
    ) -> str:
        """파드 로그 tail 줄 반환. 실패 시 빈 문자열 반환."""
        loop = asyncio.get_event_loop()
        try:
            logs = await loop.run_in_executor(
                None,
                lambda: self._core.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=tail,
                    _preload_content=True,
                ),
            )
            return logs or ""
        except ApiException as exc:
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

    # ── 복구 명령 ─────────────────────────────────────────────────

    async def rollout_restart(self, namespace: str, deploy_name: str) -> tuple[int, str]:
        """kubectl rollout restart deployment/<name> -n <ns>"""
        return await _run_cmd(
            ["kubectl", "--context", self.context,
             "rollout", "restart", f"deployment/{deploy_name}",
             "-n", namespace]
        )

    async def rollout_undo(self, namespace: str, deploy_name: str) -> tuple[int, str]:
        """kubectl rollout undo deployment/<name> -n <ns>"""
        return await _run_cmd(
            ["kubectl", "--context", self.context,
             "rollout", "undo", f"deployment/{deploy_name}",
             "-n", namespace]
        )

    async def scale_deployment(
        self, namespace: str, deploy_name: str, replicas: int
    ) -> tuple[int, str]:
        """kubectl scale deployment/<name> --replicas=N -n <ns>"""
        return await _run_cmd(
            ["kubectl", "--context", self.context,
             "scale", f"deployment/{deploy_name}",
             f"--replicas={replicas}", "-n", namespace]
        )

    async def helm_rollback(self, namespace: str, release: str) -> tuple[int, str]:
        """helm rollback <release> --wait --namespace <ns>"""
        return await _run_cmd(
            ["helm", "--kube-context", self.context,
             "rollback", release, "--wait",
             "--namespace", namespace]
        )

    async def run_arbitrary(self, cmd: list[str]) -> tuple[int, str]:
        """임의의 kubectl/helm 명령 실행 (executor.py에서 호출)"""
        # 컨텍스트 플래그가 없으면 주입
        if "kubectl" in cmd[0] and "--context" not in cmd:
            cmd = [cmd[0], "--context", self.context] + cmd[1:]
        return await _run_cmd(cmd)


async def _run_cmd(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    """비동기 subprocess 실행, (returncode, output) 반환"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode(errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        return -1, f"[타임아웃: {timeout}초 초과]"
