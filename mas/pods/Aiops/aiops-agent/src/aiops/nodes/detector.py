"""
nodes/detector.py — DETECT 노드
수집된 파드 목록에서 5가지 이상 패턴을 감지한다.
감지된 파드의 로그를 즉시 수집해 raw_logs에 추가한다.

감지 패턴:
  1. CrashLoopBackOff  (restartCount >= CRASH_THRESHOLD)
  2. OOMKilled         (lastState.terminated.reason == OOMKilled)
  3. ImagePullBackOff  (state.waiting.reason in {ImagePullBackOff, ErrImagePull})
  4. PendingTimeout    (phase == Pending AND age > PENDING_TIMEOUT_SEC)
  5. Evicted           (status.reason == Evicted)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from ..state import AgentState, IncidentEvent
from ..tools.k8s_client import K8sClient


def _check_pod(pod: dict[str, Any], vpc: str) -> IncidentEvent | None:
    """
    단일 파드 dict를 검사해 이상이 있으면 IncidentEvent 반환,
    없으면 None 반환.
    """
    metadata = pod.get("metadata", {})
    ns = metadata.get("namespace", "unknown")
    name = metadata.get("name", "unknown")
    node = pod.get("spec", {}).get("node_name") or pod.get("spec", {}).get("nodeName", "unknown")
    now_iso = datetime.now(timezone.utc).isoformat()

    status = pod.get("status", {})

    # ── 5. Evicted ────────────────────────────────────────────────
    if status.get("reason") == "Evicted":
        return IncidentEvent(
            pod=f"{ns}/{name}", node=node, vpc=vpc,
            reason="Evicted", count=0, timestamp=now_iso,
        )

    # ── 4. PendingTimeout ─────────────────────────────────────────
    if status.get("phase") == "Pending":
        ct_str = metadata.get("creation_timestamp") or metadata.get("creationTimestamp")
        if ct_str:
            try:
                ct = datetime.fromisoformat(str(ct_str).replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - ct).total_seconds()
                if age > settings.PENDING_TIMEOUT_SEC:
                    return IncidentEvent(
                        pod=f"{ns}/{name}", node=node, vpc=vpc,
                        reason="PendingTimeout", count=0, timestamp=now_iso,
                    )
            except (ValueError, TypeError):
                pass

    # ── 컨테이너 상태 순회 ────────────────────────────────────────
    container_statuses = status.get("container_statuses") or status.get("containerStatuses", [])
    for cs in container_statuses:
        restart_count = cs.get("restart_count") or cs.get("restartCount", 0)
        cs_state = cs.get("state", {})
        waiting = cs_state.get("waiting", {}) or {}
        last_state = cs.get("last_state") or cs.get("lastState", {})
        last_terminated = (last_state.get("terminated") or {}) if last_state else {}

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
    k8s_ops = K8sClient(context=settings.OPS_KUBE_CONTEXT)
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

        # 장애 파드 로그 수집
        ns, pod_name = event["pod"].split("/", 1)
        try:
            logs = await k8s_ops.get_pod_logs(ns, pod_name, tail=200)
            k8s_events = await k8s_ops.get_pod_events(ns, pod_name)
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
