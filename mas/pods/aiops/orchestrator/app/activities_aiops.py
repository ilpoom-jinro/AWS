"""
AIOps 팀 소유 Activities — detect_incident, analyze_root_cause, verify_recovery
=================================================================================
이 파일은 AIOps 팀이 v1.3.0 구현체로 교체한다.
Platform Core(activities_platform.py)와 파일을 분리해 덮어쓰기 사고를 방지한다.

교체 방법:
    1. 이 파일의 각 함수 본문을 v1.3.0 실제 구현으로 교체한다.
    2. `raise NotImplementedError(...)` 줄을 삭제하고 실제 로직을 넣으면 된다.
    3. worker.py는 건드리지 않아도 된다 (이미 이 파일을 import).
"""

from __future__ import annotations

from temporalio import activity

from contracts.models import (
    AnomalyReport,
    DetectIncidentInput,
    IncidentContext,
    RecoveryVerification,
)


@activity.defn(name="detect_incident")
async def detect_incident(input: DetectIncidentInput) -> IncidentContext:
    """
    TODO(AIOps 팀): Kubernetes 장애 탐지 구현체로 교체.
    AIOps v1.3.0의 detector 코드를 이 Activity에 연결한다.
    """
    raise NotImplementedError(
        "detect_incident는 AIOps 팀이 v1.3.0 구현체로 교체해야 합니다."
    )


@activity.defn(name="analyze_root_cause")
async def analyze_root_cause(incident: IncidentContext) -> AnomalyReport:
    """TODO(AIOps 팀): RCA 분석 구현체로 교체."""
    raise NotImplementedError(
        "analyze_root_cause는 AIOps 팀이 v1.3.0 구현체로 교체해야 합니다."
    )


@activity.defn(name="verify_recovery")
async def verify_recovery(incident: IncidentContext) -> RecoveryVerification:
    """TODO(AIOps 팀): 복구 검증 구현체로 교체."""
    raise NotImplementedError(
        "verify_recovery는 AIOps 팀이 v1.3.0 구현체로 교체해야 합니다."
    )
