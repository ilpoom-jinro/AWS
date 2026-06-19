"""
activities.py — Temporal Activity 등록 래퍼

AIOpsActivities Protocol(contracts/activity_interfaces.py)을 구현한다.
Worker에 등록되는 실제 @activity.defn 함수들.

[MAS 권한 경계]
- detect_incident / analyze_root_cause / verify_recovery: AIOps가 구현
- execute_remediation / execute_rollback: Platform Core가 구현
  (mas/workflows/activities/remediation.py) — 여기서는 구현하지 않는다.
  협의 결정 2에 따라 실행 권한은 Platform Core만 보유.

노드의 순수 비즈니스 로직(nodes/)을 호출하고 결과만 반환한다
(State 외부 노출 금지 — activity_interfaces.py 규칙).
"""
from __future__ import annotations

from temporalio import activity

from contracts.models import (
    AnomalyReport,
    DetectIncidentInput,
    IncidentContext,
    RecoveryVerification,
)

from .nodes import analyzer, detector, verifier


class AIOpsActivitiesImpl:
    """AIOpsActivities Protocol 구현체."""

    @activity.defn(name="detect_incident")
    async def detect_incident(self, input: DetectIncidentInput) -> IncidentContext | None:
        return await detector.detect_incident(input)

    @activity.defn(name="analyze_root_cause")
    async def analyze_root_cause(self, incident: IncidentContext) -> AnomalyReport:
        return await analyzer.analyze_root_cause(incident)

    @activity.defn(name="verify_recovery")
    async def verify_recovery(self, incident: IncidentContext) -> RecoveryVerification:
        return await verifier.verify_recovery(incident)


# Worker 등록용 인스턴스
aiops_activities = AIOpsActivitiesImpl()
