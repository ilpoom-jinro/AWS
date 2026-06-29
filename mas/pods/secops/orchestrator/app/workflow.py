"""
SecOps Temporal Workflow
========================
LangGraph 프로토타입의 흐름을 durable Temporal Workflow로 옮긴 것.

프로토타입과의 관계:
    - 프로토타입(LangGraph): 로컬에서 흐름을 빠르게 검증한 버전
    - 여기(Temporal): 각 단계가 독립 Activity, 분기는 Workflow가 결정,
      그리고 "사람 승인"을 며칠이 걸리든 durable하게 기다림 (이게 Temporal을 쓰는 이유)

흐름:
    detect_threat
      → map_regulation
        → 위반 없음            : 보고서(조치 없음) 후 종료
        → 위반 있음            : send_approval_request (Slack)
            → signal 로 사람 결정 대기 (wait_condition, 만료 시각까지 durable)
                → 승인 + 안전   : apply_isolation → 보고서
                → 승인 but 위험 : 자동격리 보류 → 보고서
                → 거부 / 만료   : 격리 미실행 → 보고서

Temporal 결정성(Determinism) 주의:
    - Workflow 코드 안에서는 I/O 금지, 시간은 datetime.now() 대신 workflow.now() 사용
    - 그래서 AuditLog/ExecutionResult처럼 default_factory=utc_now 필드가 있는 모델을
      Workflow에서 만들 땐 occurred_at/executed_at=workflow.now()로 명시해 비결정성 제거
    - SecurityEvent 등 타임스탬프 자동 생성 모델은 Activity 안에서만 생성 (Activity는 결정성 제약 없음)
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

from temporalio import workflow

# 승인(공통 HITL) Activity가 도는 전용 task queue. slack-hitl 봇과 반드시 동일해야 함.
HITL_TASK_QUEUE = os.getenv("HITL_TASK_QUEUE", "hitl-approval-queue")

# 비결정 코드/외부 모듈은 sandbox를 통과시켜 import
with workflow.unsafe.imports_passed_through():
    from contracts.models import (
        ApprovalRequest,
        AuditLog,
        ComplianceReport,
        DetectThreatInput,
        ExecutionResult,
        GenerateComplianceReportInput,
        RegulationMapping,
        SecurityEvent,
    )
    from workflows.activity_options import ActivityName, get_activity_options
    from .activities import (
        apply_isolation,
        detect_threat,
        generate_compliance_report,
        map_regulation,
        record_audit_log,
        send_approval_request,
    )


@workflow.defn
class SecOpsWorkflow:
    def __init__(self) -> None:
        # Slack에서 들어온 사람 결정. None이면 아직 대기 중.
        self._decision: dict | None = None

    # --- Slack HITL 봇이 버튼 클릭 시 이 signal을 보냄 ---
    @workflow.signal
    def submit_approval(self, approved: bool, reviewer_id: str, reason: str = "") -> None:
        self._decision = {"approved": approved, "reviewer_id": reviewer_id, "reason": reason}

    @workflow.query
    def awaiting_approval(self) -> bool:
        return self._decision is None

    @workflow.run
    async def run(self, detect_input: DetectThreatInput) -> ComplianceReport:
        # 1) 탐지
        event: SecurityEvent = await workflow.execute_activity(
            detect_threat, detect_input,
            **get_activity_options(ActivityName.DETECT_THREAT),
        )
        await self._audit(event.workflow_id, "workflow_started", "SecOps 워크플로우 시작",
                          {"threat_type": event.threat_type})

        # 2) 규제 매핑 (RAG + Claude)
        mapping: RegulationMapping = await workflow.execute_activity(
            map_regulation, event,
            **get_activity_options(ActivityName.MAP_REGULATION),
        )
        await self._audit(event.workflow_id, "analysis_completed", "규제 매핑 완료",
                          {"violations": len(mapping.violated_regulations),
                           "blast_radius_safe": mapping.blast_radius_safe})

        # 3) 분기 — 위반 없으면 조치 없이 종료
        if not mapping.violated_regulations:
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken="규정 위반 아님 — 조치 없음",
                executed_at=workflow.now(),
            )
            return await self._finish(event, mapping, result)

        # 위반 → Slack 승인 요청
        approval_req = ApprovalRequest(
            workflow_id=event.workflow_id, scenario="secops", severity="high",
            summary=f"보안 격리 승인 요청: {event.source_pod}",
            detail=mapping.violation_description,
            regulation_mapping=mapping,           # secops는 regulation_mapping 필수
        )
        ticket = await workflow.execute_activity(
            send_approval_request, approval_req,
            task_queue=HITL_TASK_QUEUE,   # 공통 슬랙 봇 큐로 라우팅 (.activities 스텁은 run_demo용)
            **get_activity_options(ActivityName.SEND_APPROVAL_REQUEST),
        )
        await self._audit(event.workflow_id, "approval_requested", "Slack 승인 요청 전송",
                          {"slack_message_ts": ticket.slack_message_ts})

        # 사람 결정을 durable하게 대기 (만료 시각까지). 워커가 죽어도 상태 보존.
        # TODO(다음): reminder_after_hours 경과 시 send_reminder를 race로 호출
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(hours=approval_req.expire_after_hours),
            )
        except asyncio.TimeoutError:
            await self._audit(event.workflow_id, "approval_timeout", "승인 시간 초과", {})
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken="승인 시간 초과 — 격리 미실행",
                executed_at=workflow.now(),
            )
            return await self._finish(event, mapping, result)

        # 4) 결정 반영
        approved = self._decision["approved"]
        if approved:
            await self._audit(event.workflow_id, "approval_granted", "승인됨",
                              {"reviewer": self._decision["reviewer_id"]})
            if mapping.blast_radius_safe:
                result = await workflow.execute_activity(
                    apply_isolation, mapping,
                    **get_activity_options(ActivityName.APPLY_ISOLATION),
                )
                await self._audit(event.workflow_id, "action_executed", "격리 실행",
                                  {"success": result.success})
            else:
                result = ExecutionResult(
                    workflow_id=event.workflow_id, success=False,
                    action_taken="승인됐으나 blast radius 위험 → 자동격리 보류",
                    executed_at=workflow.now(),
                )
        else:
            await self._audit(event.workflow_id, "approval_denied", "거부됨",
                              {"reviewer": self._decision["reviewer_id"]})
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken="승인 거부 → 격리 미실행",
                executed_at=workflow.now(),
            )

        return await self._finish(event, mapping, result)

    # --- 보고서 생성 + 완료 감사 로그 ---
    async def _finish(
        self,
        event: SecurityEvent,
        mapping: RegulationMapping,
        result: ExecutionResult,
    ) -> ComplianceReport:
        report = await workflow.execute_activity(
            generate_compliance_report,
            GenerateComplianceReportInput(event=event, mapping=mapping, result=result),
            **get_activity_options(ActivityName.GENERATE_COMPLIANCE_REPORT),
        )
        await self._audit(event.workflow_id, "workflow_completed", "워크플로우 완료",
                          {"isolation_applied": report.isolation_applied})
        return report

    async def _audit(self, workflow_id: str, event_type: str, summary: str, payload: dict) -> None:
        log = AuditLog(
            workflow_id=workflow_id, scenario="secops", event_type=event_type,
            actor="secops-workflow", summary=summary, payload=payload,
            occurred_at=workflow.now(),           # Workflow 결정성: now() 명시
        )
        await workflow.execute_activity(
            record_audit_log, log,
            **get_activity_options(ActivityName.RECORD_AUDIT_LOG),
        )
