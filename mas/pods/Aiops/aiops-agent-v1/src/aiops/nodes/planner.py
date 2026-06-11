"""
nodes/planner.py — PLAN 노드

[v0.2 수정사항]
- _extract_deploy_name: ReplicaSet 해시 정규식을 [0-9a-f]{5,10}으로 보정
  (실제 RS 해시는 5~10자 가변) + fallback 로직 단순화
- _context_for 내부 중복 import 제거
"""
from __future__ import annotations

import json
import logging
import re

from ..config import settings
from ..state import AgentState, IncidentEvent, RecoveryPlan

logger = logging.getLogger(__name__)

STRATEGY_PRIORITY = {
    "restart": 1,
    "scale_out": 2,
    "rollback": 3,
    "investigate": 4,
}

# ReplicaSet pod-template-hash: 영숫자 5~10자 (소문자/숫자)
_RS_HASH_RE = re.compile(r"^[0-9a-z]{5,10}$")
# 파드 suffix: 영숫자 5자
_POD_SUFFIX_RE = re.compile(r"^[0-9a-z]{5}$")


def _extract_deploy_name(pod_name: str) -> str:
    """
    파드 이름에서 Deployment 이름 추출.
      backend-6d4f7c8b9-xkj2p      → backend
      demo-app-backend-7f9d5-ab12c → demo-app-backend
      standalone-pod               → standalone-pod (그대로)
    """
    parts = pod_name.rsplit("-", 2)
    if len(parts) == 3 and _RS_HASH_RE.match(parts[1]) and _POD_SUFFIX_RE.match(parts[2]):
        return parts[0]
    # StatefulSet (name-0) 또는 비표준 이름 → 마지막 토큰만 제거 시도
    parts2 = pod_name.rsplit("-", 1)
    if len(parts2) == 2 and parts2[1].isdigit():
        return parts2[0]
    return pod_name


def _context_for(vpc: str) -> str:
    return settings.OPS_KUBE_CONTEXT if vpc == "vpc2" else settings.SERVICE_KUBE_CONTEXT


def _build_restart_plan(event: IncidentEvent) -> RecoveryPlan:
    ns, pod = event["pod"].split("/", 1)
    deploy = _extract_deploy_name(pod)
    return RecoveryPlan(
        strategy="restart",
        target=f"deployment/{deploy}",
        command=[
            "kubectl", "--context", _context_for(event["vpc"]),
            "rollout", "restart", f"deployment/{deploy}",
            "-n", ns,
        ],
        priority=1,
        reason=(
            f"CrashLoop 감지: {event['reason']} "
            f"(재시작 {event['count']}회) — Rolling restart로 임시 복구"
        ),
    )


def _build_scale_plan(event: IncidentEvent, current_replicas: int = 2) -> RecoveryPlan:
    ns, pod = event["pod"].split("/", 1)
    deploy = _extract_deploy_name(pod)
    new_replicas = current_replicas + 2
    return RecoveryPlan(
        strategy="scale_out",
        target=f"deployment/{deploy}",
        command=[
            "kubectl", "--context", _context_for(event["vpc"]),
            "scale", f"deployment/{deploy}",
            f"--replicas={new_replicas}", "-n", ns,
        ],
        priority=2,
        reason=(
            f"OOMKilled 감지: 메모리 부족 — "
            f"레플리카 {current_replicas}→{new_replicas}로 부하 분산"
        ),
    )


def _build_rollback_plan(event: IncidentEvent, release: str = "") -> RecoveryPlan:
    ns, pod = event["pod"].split("/", 1)
    deploy = _extract_deploy_name(pod)
    helm_release = release or deploy
    return RecoveryPlan(
        strategy="rollback",
        target=f"helm/{helm_release}",
        command=[
            "helm", "--kube-context", _context_for(event["vpc"]),
            "rollback", helm_release, "--wait",
            "--namespace", ns,
        ],
        priority=3,
        reason="최근 배포 후 장애 발생 → Helm 이전 버전으로 롤백",
    )


def _build_investigate_plan(event: IncidentEvent, confidence: float) -> RecoveryPlan:
    return RecoveryPlan(
        strategy="investigate",
        target=event["pod"],
        command=[],
        priority=4,
        reason=(
            f"RCA 신뢰도 낮음 ({confidence:.0%}) — "
            "수동 조사 필요. kubectl describe pod / kubectl logs 확인 권고."
        ),
    )


async def run(state: AgentState) -> AgentState:
    """PLAN 노드 진입점"""
    try:
        rca = json.loads(state["rca_report"])
    except (json.JSONDecodeError, KeyError, TypeError):
        rca = {"recommended_strategy": "investigate", "confidence": 0.0}

    strategy = rca.get("recommended_strategy", "investigate")
    try:
        confidence = float(rca.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    plans: list[RecoveryPlan] = []

    for event in state["events"]:
        if confidence < settings.RCA_CONFIDENCE_MIN:
            plans.append(_build_investigate_plan(event, confidence))
            continue

        if strategy == "restart":
            plans.append(_build_restart_plan(event))
        elif strategy == "scale_out":
            plans.append(_build_scale_plan(event))
        elif strategy == "rollback":
            plans.append(_build_rollback_plan(event))
        else:
            plans.append(_build_investigate_plan(event, confidence))

    plans.sort(key=lambda p: STRATEGY_PRIORITY.get(p["strategy"], 99))

    logger.info("복구 계획 수립 완료: %d개", len(plans))
    return {**state, "plans": plans}
