"""
mappers/anomaly.py — K8s 상태 ↔ contracts anomaly_type 매핑

팀 contracts.models.IncidentContext.anomaly_type (김민수님 반영 완료, 6월 18일):
    crashloop_backoff, oom_killed, high_latency,
    image_pull_backoff, pending_timeout, evicted

이 모듈은 detector가 K8s API에서 읽은 원시 reason 문자열을
contracts 표준 anomaly_type으로 변환하는 단일 진입점이다.
"""
from __future__ import annotations

from typing import Literal

# contracts.models.IncidentContext.anomaly_type 과 1:1 대응
AnomalyType = Literal[
    "crashloop_backoff",
    "oom_killed",
    "high_latency",
    "image_pull_backoff",
    "pending_timeout",
    "evicted",
]

# K8s 원시 reason → contracts anomaly_type
ANOMALY_TYPE_MAP: dict[str, AnomalyType] = {
    "CrashLoopBackOff": "crashloop_backoff",
    "OOMKilled": "oom_killed",
    "ImagePullBackOff": "image_pull_backoff",
    "ErrImagePull": "image_pull_backoff",
    "PendingTimeout": "pending_timeout",
    "Evicted": "evicted",
}


def to_anomaly_type(k8s_reason: str) -> AnomalyType | None:
    """K8s reason 문자열을 contracts anomaly_type으로 변환.

    매핑되지 않는 reason이면 None (탐지 대상 아님).
    """
    return ANOMALY_TYPE_MAP.get(k8s_reason)
