"""
nodes/verifier.py — verify_recovery Activity 구현

AIOpsActivities.verify_recovery(IncidentContext) -> RecoveryVerification

[MAS 정합]
- 5분 대기는 Workflow가 timer로 처리하는 것이 원칙이므로,
  이 Activity는 "현재 시점 상태 재검사"만 수행한다.
  (Workflow: execute_remediation → workflow.sleep(300) → verify_recovery)
- 출력: contracts.RecoveryVerification (recovered, needs_rollback)
- 읽기 전용 K8sCollector 사용

원래 파드명이 rollout으로 바뀌어도 Deployment prefix로 추적한다.
"""
from __future__ import annotations

import logging

from contracts.models import IncidentContext, RecoveryVerification

from ..config import settings
from ..k8s_collector import K8sCollector
from ..nodes.detector import _detect_reason

logger = logging.getLogger(__name__)


def _deploy_prefix(pod_name: str) -> str:
    """파드명에서 Deployment prefix 추출 (ReplicaSet 해시 제거)."""
    import re
    parts = pod_name.rsplit("-", 2)
    if len(parts) == 3 and re.fullmatch(r"[0-9a-z]{5,10}", parts[1]):
        return parts[0]
    return pod_name


async def verify_recovery(incident: IncidentContext) -> RecoveryVerification:
    """verify_recovery Activity 진입점. 현재 상태 재검사."""
    context = (
        settings.OPS_KUBE_CONTEXT
        if incident.cluster_name == settings.OPS_EKS_CLUSTER_NAME
        else settings.SERVICE_KUBE_CONTEXT
    )
    collector = K8sCollector(context=context)
    pods = await collector.list_namespace_pods(incident.namespace)

    prefix = _deploy_prefix(incident.pod_name)
    still_failing = []
    for pod in pods:
        name = pod.get("metadata", {}).get("name", "")
        if not name.startswith(prefix):
            continue
        if _detect_reason(pod) is not None:
            still_failing.append(name)

    recovered = len(still_failing) == 0
    reason = (
        f"{prefix} 계열 파드 정상화 확인"
        if recovered
        else f"이상 재감지: {', '.join(still_failing)}"
    )

    return RecoveryVerification(
        workflow_id=incident.workflow_id,
        recovered=recovered,
        needs_rollback=not recovered,
        confidence=0.9 if recovered else 0.8,
        reason=reason,
    )
