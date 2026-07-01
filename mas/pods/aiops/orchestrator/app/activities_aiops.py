"""
AIOps 팀 소유 Activities — detect_incident, analyze_root_cause, verify_recovery
=================================================================================
AIOps v1.3.0 구현체. 순수 로직은 nodes/ 에 있고, 이 파일은 각 노드를
@activity.defn 으로 래핑해 Temporal Worker에 노출한다.

Platform Core(activities_platform.py)와 파일을 분리해 덮어쓰기 사고를 방지한다.
worker.py는 이 파일을 import하므로 수정하지 않아도 된다.

[MAS 권한 경계]
- detect_incident / analyze_root_cause / verify_recovery: AIOps 소유 (이 파일)
- execute_remediation / execute_rollback / record_audit_log: Platform Core 소유
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


@activity.defn(name="detect_incident")
async def detect_incident(input: DetectIncidentInput) -> IncidentContext | None:
    """Kubernetes 장애 탐지. 장애가 없으면 None을 반환한다.

    상태 이상(CrashLoop/OOM/ImagePull 등)뿐 아니라, 상태 이상이 없는
    Running 파드의 Istio P95 지연 기반 high_latency까지 탐지한다(v1.3.0).
    """
    return await detector.detect_incident(input)


@activity.defn(name="analyze_root_cause")
async def analyze_root_cause(incident: IncidentContext) -> AnomalyReport:
    """Bedrock 기반 RCA. Thanos 메트릭을 교차검증해 조치 전략을 결정한다.

    scale_out은 HPA patch 방식으로 strategy_detail에 인코딩되어
    Platform Core(execute_remediation)가 파싱한다(v1.3.0).
    """
    return await analyzer.analyze_root_cause(incident)


@activity.defn(name="verify_recovery")
async def verify_recovery(incident: IncidentContext) -> RecoveryVerification:
    """조치 후 복구 여부를 재검증한다."""
    return await verifier.verify_recovery(incident)
