"""
nodes/detector.py — detect_incident Activity 구현

AIOpsActivities.detect_incident(DetectIncidentInput) -> IncidentContext

[MAS 정합]
- 입력: contracts.DetectIncidentInput (cluster_name, namespace)
- 출력: contracts.IncidentContext (단일 최우선 장애) 또는 None
- anomaly_type은 mappers.to_anomaly_type로 표준값 변환
- recent_logs는 최대 50줄 (contracts 제한)
- 읽기 전용 K8sCollector만 사용 (실행 권한 없음)

탐지 패턴 (협의 후 6종):
  CrashLoopBackOff, OOMKilled, ImagePullBackOff/ErrImagePull,
  PendingTimeout(>10분), Evicted
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from contracts.models import DetectIncidentInput, IncidentContext

from ..config import settings
from ..k8s_collector import K8sCollector
from ..metrics_collector import MetricsCollector
from ..mappers import to_anomaly_type

CRASH_THRESHOLD = 3
PENDING_TIMEOUT_SEC = 600
MAX_LOG_LINES = 50  # contracts.IncidentContext.recent_logs max_length

EXCLUDED_NAMESPACES = {
    "kube-system", "kube-public", "kube-node-lease",
    "observability", "aiops",
}


def _parse_timestamp(raw: Any) -> datetime | None:
    """datetime 객체 또는 ISO 문자열 모두 처리 (k8s SDK to_dict는 datetime 반환)."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _detect_reason(pod: dict[str, Any]) -> tuple[str, int] | None:
    """파드 dict에서 (k8s_reason, restart_count) 추출. 정상이면 None."""
    status = pod.get("status", {})

    # Evicted
    if status.get("reason") == "Evicted":
        return "Evicted", 0

    # PendingTimeout
    if status.get("phase") == "Pending":
        ct = _parse_timestamp(
            pod.get("metadata", {}).get("creation_timestamp")
            or pod.get("metadata", {}).get("creationTimestamp")
        )
        if ct:
            age = (datetime.now(timezone.utc) - ct).total_seconds()
            if age > PENDING_TIMEOUT_SEC:
                return "PendingTimeout", 0

    container_statuses = (
        status.get("container_statuses") or status.get("containerStatuses") or []
    )
    for cs in container_statuses:
        restart_count = cs.get("restart_count") or cs.get("restartCount", 0)
        waiting = (cs.get("state", {}) or {}).get("waiting", {}) or {}
        last_state = cs.get("last_state") or cs.get("lastState", {}) or {}
        last_term = (last_state.get("terminated") or {}) if last_state else {}

        if waiting.get("reason") == "CrashLoopBackOff" and restart_count >= CRASH_THRESHOLD:
            return "CrashLoopBackOff", restart_count
        if last_term.get("reason") == "OOMKilled":
            return "OOMKilled", restart_count
        if waiting.get("reason") in ("ImagePullBackOff", "ErrImagePull"):
            return "ImagePullBackOff", 0

    return None


async def detect_incident(input: DetectIncidentInput) -> IncidentContext | None:
    """detect_incident Activity 진입점.

    지정된 cluster/namespace에서 최우선 장애 1건을 IncidentContext로 반환.
    장애 없으면 None.
    """
    context = (
        settings.OPS_KUBE_CONTEXT
        if input.cluster_name == settings.OPS_EKS_CLUSTER_NAME
        else settings.SERVICE_KUBE_CONTEXT
    )
    collector = K8sCollector(context=context)
    pods = await collector.list_namespace_pods(input.namespace)

    for pod in pods:
        ns = pod.get("metadata", {}).get("namespace", "")
        if ns in EXCLUDED_NAMESPACES:
            continue

        detected = _detect_reason(pod)
        if not detected:
            continue

        k8s_reason, restart_count = detected
        anomaly_type = to_anomaly_type(k8s_reason)
        if anomaly_type is None:
            continue

        pod_name = pod.get("metadata", {}).get("name", "")

        # 로그 수집 (CrashLoop은 previous 폴백) — 최대 50줄
        logs = await collector.get_pod_logs(
            ns, pod_name, tail=MAX_LOG_LINES,
            previous=(k8s_reason == "CrashLoopBackOff"),
        )
        log_lines = [ln for ln in logs.splitlines() if ln][:MAX_LOG_LINES]

        # 메트릭 수집 (Thanos Query, 읽기 전용) — IncidentContext 메트릭 필드 채움
        metrics = await MetricsCollector(settings.THANOS_QUERY_URL).collect_pod_metrics(
            cluster=input.cluster_name, namespace=ns, pod=pod_name,
        )

        return IncidentContext(
            cluster_name=input.cluster_name,
            namespace=ns,
            pod_name=pod_name,
            anomaly_type=anomaly_type,
            restart_count=restart_count,
            recent_logs=log_lines,
            cpu_usage_current=metrics["cpu_usage_current"],
            memory_usage_current=metrics["memory_usage_current"],
            error_rate=metrics["error_rate"],
        )

    return None
