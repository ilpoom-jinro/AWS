"""
nodes/verifier.py — VERIFY 노드
복구 실행 후 VERIFY_WAIT_SEC(기본 5분) 대기한 뒤
원래 장애 파드들을 재수집해 이상이 재발했는지 확인한다.

verify_ok=True  → monitor로 정상 복귀
verify_ok=False → rollback 노드로 자동 분기
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from ..state import AgentState
from ..tools.k8s_client import K8sClient
from ..tools.slack import SlackClient
from .detector import _check_pod

logger = logging.getLogger(__name__)
_slack = SlackClient(settings.SLACK_BOT_TOKEN)


async def run(state: AgentState) -> AgentState:
    """VERIFY 노드 진입점"""
    wait_min = settings.VERIFY_WAIT_SEC // 60

    await _slack.post_message(
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

    # 원래 장애 파드에 이상 재발 여부 확인
    new_events = []
    for pod, vpc in [(p, "vpc2") for p in pods_ops] + [(p, "vpc1") for p in pods_svc]:
        metadata = pod.get("metadata", {})
        ns = metadata.get("namespace", "")
        name = metadata.get("name", "")
        if f"{ns}/{name}" in original_pods:
            ev = _check_pod(pod, vpc)
            if ev:
                new_events.append(ev)

    verify_ok = len(new_events) == 0

    if verify_ok:
        msg = f"✅ {wait_min}분 재모니터링 완료 — 정상 확인. 모니터링 루프로 복귀합니다."
    else:
        pod_list = ", ".join(e["pod"] for e in new_events)
        msg = (
            f"🚨 이상 재감지 ({len(new_events)}건): {pod_list}\n"
            f"자동 롤백을 진행합니다."
        )

    await _slack.post_message(settings.SLACK_CHANNEL, msg)
    logger.info("VERIFY 결과: verify_ok=%s, 재감지=%d건", verify_ok, len(new_events))

    return {**state, "verify_ok": verify_ok}
