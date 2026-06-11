"""
nodes/verifier.py — VERIFY 노드

[v0.2 수정사항]
- Slack 클라이언트 lazy 초기화 (get_slack)
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from ..state import AgentState
from ..tools.k8s_client import K8sClient
from ..tools.slack import get_slack
from .detector import _check_pod

logger = logging.getLogger(__name__)


async def run(state: AgentState) -> AgentState:
    """VERIFY 노드 진입점 — 복구 후 5분 재모니터링"""
    slack = get_slack()
    wait_min = settings.VERIFY_WAIT_SEC // 60

    await slack.post_message(
        settings.SLACK_CHANNEL,
        f"⏳ {wait_min}분 대기 후 재모니터링을 시작합니다...",
    )

    await asyncio.sleep(settings.VERIFY_WAIT_SEC)

    # 원래 장애 파드 식별자 집합
    original_pods: set[str] = {e["pod"] for e in state["events"]}

    # 두 클러스터 재수집
    k8s_ops = K8sClient(context=settings.OPS_KUBE_CONTEXT)
    k8s_svc = K8sClient(context=settings.SERVICE_KUBE_CONTEXT)

    pods_ops, pods_svc = await asyncio.gather(
        k8s_ops.list_pods_all_namespaces(),
        k8s_svc.list_pods_all_namespaces(),
    )

    # 동일 파드(또는 동일 워크로드의 새 파드)에 이상 재발 여부 확인
    # rollout restart 시 파드 이름이 바뀌므로, 원래 파드의 prefix(Deployment 단위)로 비교
    original_prefixes = {p.rsplit("-", 2)[0] for p in original_pods}

    new_events = []
    for pod, vpc in [(p, "vpc2") for p in pods_ops] + [(p, "vpc1") for p in pods_svc]:
        metadata = pod.get("metadata") or {}
        ns = metadata.get("namespace", "")
        name = metadata.get("name", "")
        full = f"{ns}/{name}"
        prefix = full.rsplit("-", 2)[0]
        if full in original_pods or prefix in original_prefixes:
            ev = _check_pod(pod, vpc)
            if ev:
                new_events.append(ev)

    verify_ok = len(new_events) == 0

    if verify_ok:
        msg = f"✅ {wait_min}분 재모니터링 완료 — 정상 확인."
    else:
        pod_list = ", ".join(e["pod"] for e in new_events)
        msg = (
            f"🚨 이상 재감지 ({len(new_events)}건): {pod_list}\n"
            f"자동 롤백을 진행합니다."
        )

    await slack.post_message(settings.SLACK_CHANNEL, msg)
    logger.info("VERIFY 결과: verify_ok=%s, 재감지=%d건", verify_ok, len(new_events))

    return {**state, "verify_ok": verify_ok}
