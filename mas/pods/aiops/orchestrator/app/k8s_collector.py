"""
k8s_collector.py — 읽기 전용 K8s 수집 도구

[MAS 권한 경계] Agent는 실행 권한이 없다 (activity_interfaces.py 명시).
따라서 이 모듈은 조회(list/read)만 제공하며, rollout restart/undo/scale 같은
변경 명령은 제공하지 않는다. 실제 실행은 Platform Core Activity가 담당한다.

멀티 클러스터 접근 전략 (context 기반 분기):
- ops(자기 클러스터):    load_incluster_config() → ServiceAccount 토큰
- service(원격 클러스터): boto3로 EKS bearer 토큰을 생성하고 describe-cluster의
                          endpoint/CA로 원격 접근. (Pod Identity가 부여한 IAM
                          자격증명 사용, VPC peering으로 네트워크 도달)
                          aws CLI 불필요 — boto3만으로 토큰 서명.
"""
from __future__ import annotations

import asyncio
import base64
import tempfile
from typing import Any

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from .config import settings


def _make_incluster_api_client() -> client.ApiClient:
    """ops(자기 클러스터): in-cluster 설정. 로컬 개발 시 kubeconfig 폴백."""
    try:
        k8s_config.load_incluster_config()
        return client.ApiClient()
    except k8s_config.ConfigException:
        return k8s_config.new_client_from_config()


def _generate_eks_token(cluster_name: str, region: str) -> str:
    """boto3로 EKS bearer 토큰을 생성한다 (aws CLI 불필요).

    EKS 토큰 = STS GetCallerIdentity presigned URL에 EKS 클러스터를 헤더로 묶어
    base64url 인코딩한 것. Pod Identity가 부여한 자격증명으로 서명된다.
    """
    import boto3
    from botocore.signers import RequestSigner

    session = boto3.session.Session()
    sts = session.client("sts", region_name=region)
    signer = RequestSigner(
        sts.meta.service_model.service_id,
        region,
        "sts",
        "v4",
        session.get_credentials(),
        session.events,
    )
    params = {
        "method": "GET",
        "url": (
            f"https://sts.{region}.amazonaws.com/"
            f"?Action=GetCallerIdentity&Version=2011-06-15"
        ),
        "body": {},
        "headers": {"x-k8s-aws-id": cluster_name},
        "context": {},
    }
    signed_url = signer.generate_presigned_url(
        params, region_name=region, expires_in=60, operation_name=""
    )
    token = "k8s-aws-v1." + base64.urlsafe_b64encode(
        signed_url.encode("utf-8")
    ).decode("utf-8").rstrip("=")
    return token


def _make_remote_api_client(cluster_name: str, region: str) -> client.ApiClient:
    """service(원격 클러스터): describe-cluster로 endpoint/CA를 얻고,
    boto3로 생성한 bearer 토큰으로 원격 ApiClient를 구성한다.

    해당 IAM role이 원격 클러스터 access entry에 등록돼 있어야 인증된다.
    """
    import boto3

    eks = boto3.client("eks", region_name=region)
    desc = eks.describe_cluster(name=cluster_name)["cluster"]
    endpoint = desc["endpoint"]
    ca_data = desc["certificateAuthority"]["data"]

    token = _generate_eks_token(cluster_name, region)

    # CA 인증서를 임시 파일로 (kubernetes 클라이언트가 파일 경로 요구)
    ca_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".crt", delete=False)
    ca_file.write(base64.b64decode(ca_data))
    ca_file.flush()

    cfg = client.Configuration()
    cfg.host = endpoint
    cfg.ssl_ca_cert = ca_file.name
    cfg.api_key = {"authorization": f"Bearer {token}"}
    return client.ApiClient(cfg)


def _make_api_client(context: str) -> client.ApiClient:
    """context에 따라 ops(in-cluster) / service(원격) 접근을 분기."""
    if context == settings.SERVICE_KUBE_CONTEXT:
        return _make_remote_api_client(
            settings.SERVICE_EKS_CLUSTER_NAME, settings.AWS_REGION
        )
    return _make_incluster_api_client()


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
