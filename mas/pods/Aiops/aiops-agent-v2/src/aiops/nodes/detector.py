"""
nodes/detector.py — DETECT 노드

[v0.2 수정사항]
- kubernetes SDK to_dict()는 creation_timestamp를 datetime 객체로 반환
  → 기존 문자열 파싱 코드가 동작하지 않음 → datetime/str 모두 처리
- 장애 파드 로그를 무조건 Ops 클라이언트로 수집하던 버그
  → 파드가 속한 VPC의 클러스터 클라이언트로 수집하도록 수정
- node_name 키: SDK to_dict()는 snake_case(node_name) → 우선 조회

감지 패턴 5종:
  1. CrashLoopBackOff  (restartCount >= CRASH_THRESHOLD)
  2. OOMKilled         (lastState.terminated.reason == OOMKilled)
  3. ImagePullBackOff  (state.waiting.reason in {ImagePullBackOff, ErrImagePull})
  4. PendingTimeout    (phase == Pending AND age > PENDING_TIMEOUT_SEC)
  5. Evicted           (status.reason == Evicted)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from ..state import AgentState, IncidentEvent
from ..tools.k8s_client import K8sClient

logger = logging.getLogger(__name__)

# 시스템 네임스페이스는 감지 제외 (자기 자신/인프라 컴포넌트 오탐 방지)
EXCLUDED_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease", "aiops"}


def _parse_timestamp(raw: Any) -> datetime | None:
    """datetime 객체 또는 ISO 문자열 모두 처리"""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _check_pod(pod: dict[str, Any], vpc: str) -> IncidentEvent | None:
    """단일 파드 dict 검사. 이상 시 IncidentEvent, 정상 시 None."""
    metadata = pod.get("metadata") or {}
    ns = metadata.get("namespace", "unknown")
    name = metadata.get("name", "unknown")

    if ns in EXCLUDED_NAMESPACES:
        return None

    spec = pod.get("spec") or {}
    node = spec.get("node_name") or spec.get("nodeName") or "unknown"
    now_iso = datetime.now(timezone.utc).isoformat()

    status = pod.get("status") or {}

    # ── 5. Evicted ────────────────────────────────────────────────
    if status.get("reason") == "Evicted":
        return IncidentEvent(
            pod=f"{ns}/{name}", node=node, vpc=vpc,
            reason="Evicted", count=0, timestamp=now_iso,
        )

    # ── 4. PendingTimeout ─────────────────────────────────────────
    if status.get("phase") == "Pending":
        ct = _parse_timestamp(
            metadata.get("creation_timestamp") or metadata.get("creationTimestamp")
        )
        if ct:
            age = (datetime.now(timezone.utc) - ct).total_seconds()
            if age > settings.PENDING_TIMEOUT_SEC:
                return IncidentEvent(
                    pod=f"{ns}/{name}", node=node, vpc=vpc,
                    reason="PendingTimeout", count=0, timestamp=now_iso,
                )

    # ── 컨테이너 상태 순회 ────────────────────────────────────────
    container_statuses = (
        status.get("container_statuses")
        or status.get("containerStatuses")
        or []
    )
    for cs in container_statuses:
        restart_count = cs.get("restart_count") or cs.get("restartCount") or 0
        cs_state = cs.get("state") or {}
        waiting = cs_state.get("waiting") or {}
        last_state = cs.get("last_state") or cs.get("lastState") or {}
        last_terminated = last_state.get("terminated") or {}

        # 1. CrashLoopBackOff
        if (
            waiting.get("reason") == "CrashLoopBackOff"
            and restart_count >= settings.CRASH_THRESHOLD
        ):
            return IncidentEvent(
                pod=f"{ns}/{name}", node=node, vpc=vpc,
                reason="CrashLoopBackOff", count=restart_count, timestamp=now_iso,
            )

        # 2. OOMKilled
        if last_terminated.get("reason") == "OOMKilled":
            return IncidentEvent(
                pod=f"{ns}/{name}", node=node, vpc=vpc,
                reason="OOMKilled", count=restart_count, timestamp=now_iso,
            )

        # 3. ImagePullBackOff
        if waiting.get("reason") in ("ImagePullBackOff", "ErrImagePull"):
            return IncidentEvent(
                pod=f"{ns}/{name}", node=node, vpc=vpc,
                reason="ImagePullBackOff", count=0, timestamp=now_iso,
            )

    return None


async def run(state: AgentState) -> AgentState:
    """DETECT 노드 진입점"""
    # VPC별 클라이언트 — 장애 파드 로그를 올바른 클러스터에서 수집
    clients = {
        "vpc2": K8sClient(context=settings.OPS_KUBE_CONTEXT),
        "vpc1": K8sClient(context=settings.SERVICE_KUBE_CONTEXT),
    }

    events: list[IncidentEvent] = []
    raw_logs: list[str] = list(state.get("raw_logs", []))

    all_pods = (
        [(p, "vpc2") for p in state.get("_pods_ops", [])]
        + [(p, "vpc1") for p in state.get("_pods_svc", [])]
    )

    for pod, vpc in all_pods:
        event = _check_pod(pod, vpc)
        if not event:
            continue

        events.append(event)
        logger.info("장애 감지: %s (%s)", event["pod"], event["reason"])

        # 해당 VPC 클러스터에서 로그 수집
        ns, pod_name = event["pod"].split("/", 1)
        k8s = clients.get(vpc, clients["vpc2"])
        try:
            logs = await k8s.get_pod_logs(ns, pod_name, tail=200)
            k8s_events = await k8s.get_pod_events(ns, pod_name)
            log_section = (
                f"=== 파드 로그: {event['pod']} (reason={event['reason']}) ===\n"
                f"{logs}\n"
                f"=== K8s 이벤트 ===\n"
                + "\n".join(k8s_events)
            )
            raw_logs.append(log_section)
        except Exception as exc:
            raw_logs.append(f"[로그 수집 실패: {event['pod']} — {exc}]")

    return {**state, "events": events, "raw_logs": raw_logs}
