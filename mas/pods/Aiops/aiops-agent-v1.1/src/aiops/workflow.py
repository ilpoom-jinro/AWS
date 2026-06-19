"""
workflow.py — AIOps 장애 복구 Temporal Workflow

흐름 (Workflow가 오케스트레이션):
  1. detect_incident         → IncidentContext (없으면 종료)
  2. record_audit_log(anomaly_detected)
  3. analyze_root_cause      → AnomalyReport(remediation_plan)
  4. send_approval_request   → ApprovalTicket (즉시 반환, Slack 메시지 발송)
  5. 승인 대기: signal(approval_signal) + wait_condition (최대 expire 8h)
       - reminder_after_hours(4h) 경과 시 send_reminder
       - expire_after_hours(8h) 경과 시 자동 거부(timeout)
  6. 승인 + strategy != manual → execute_remediation (Platform Core Activity)
  7. workflow.sleep(VERIFY_WAIT) → verify_recovery
  8. needs_rollback이면 execute_rollback (Platform Core Activity)
  9. record_audit_log(workflow_completed)

[MAS v2 정합 — 6월 18일 temporal.zip]
- get_activity_options는 ActivityName Enum 인자 사용
- 승인은 request_approval(블로킹) 폐기 → send_approval_request + signal/wait_condition
- ApprovalResult는 외부(slack-hitl bot)가 signal로 주입
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from contracts.models import (
        AnomalyReport,
        ApprovalRequest,
        ApprovalResult,
        ApprovalTicket,
        AuditLog,
        DetectIncidentInput,
        ExecutionResult,
        IncidentContext,
        RecoveryVerification,
    )
    from workflows.activity_options import ActivityName, get_activity_options
    from aiops.config import settings


@workflow.defn(name="AIOpsRemediationWorkflow")
class AIOpsRemediationWorkflow:
    def __init__(self) -> None:
        self._approval: ApprovalResult | None = None

    # ── Slack HITL bot이 승인/거부 결과를 주입하는 signal ──
    @workflow.signal(name="approval_result")
    async def approval_result(self, result: ApprovalResult) -> None:
        self._approval = result

    @workflow.run
    async def run(self, detect_input: DetectIncidentInput) -> str:
        # 1. 탐지
        incident: IncidentContext | None = await workflow.execute_activity(
            ActivityName.DETECT_INCIDENT,
            detect_input,
            **get_activity_options(ActivityName.DETECT_INCIDENT),
        )
        if incident is None:
            return "no_incident"

        await self._audit(incident.workflow_id, "anomaly_detected",
                          f"{incident.namespace}/{incident.pod_name} {incident.anomaly_type}")

        # 3. RCA
        report: AnomalyReport = await workflow.execute_activity(
            ActivityName.ANALYZE_ROOT_CAUSE,
            incident,
            **get_activity_options(ActivityName.ANALYZE_ROOT_CAUSE),
        )
        await self._audit(incident.workflow_id, "analysis_completed", report.summary)

        plan = report.remediation_plan
        if plan is None:
            return "no_plan"

        # 4. 승인 요청 발송 (즉시 반환되는 티켓)
        approval_req = ApprovalRequest(
            workflow_id=incident.workflow_id,
            scenario="aiops",
            severity=report.severity,
            summary=report.summary,
            detail=report.detail,
            remediation_plan=plan,
        )
        ticket: ApprovalTicket = await workflow.execute_activity(
            ActivityName.SEND_APPROVAL_REQUEST,
            approval_req,
            **get_activity_options(ActivityName.SEND_APPROVAL_REQUEST),
        )
        await self._audit(incident.workflow_id, "approval_requested", report.summary)

        # 5. 승인 대기 (signal + wait_condition)
        reminder_after = timedelta(hours=approval_req.reminder_after_hours)
        expire_after = timedelta(hours=approval_req.expire_after_hours)

        # 5-1. reminder 시점까지 대기 (그 전에 승인되면 즉시 통과)
        got_early = await workflow.wait_condition(
            lambda: self._approval is not None,
            timeout=reminder_after,
        )
        # 5-2. 아직 미응답이면 reminder 발송 후 남은 시간 대기
        if not got_early and self._approval is None:
            await workflow.execute_activity(
                ActivityName.SEND_REMINDER,
                ticket,
                **get_activity_options(ActivityName.SEND_REMINDER),
            )
            await workflow.wait_condition(
                lambda: self._approval is not None,
                timeout=expire_after - reminder_after,
            )

        # 5-3. 만료 판정
        if self._approval is None:
            await self._audit(incident.workflow_id, "approval_timeout",
                              "8시간 무응답 — 자동 거부")
            return "expired"

        if not self._approval.approved:
            await self._audit(incident.workflow_id, "approval_denied",
                              self._approval.reason)
            return "denied"

        await self._audit(incident.workflow_id, "approval_granted",
                          self._approval.reviewer_id)

        # manual 전략은 사람이 직접 처리 — 자동 실행 안 함
        if plan.strategy == "manual":
            return "manual_handover"

        # 6. 복구 실행 (Platform Core Activity, heartbeat 필요)
        exec_result: ExecutionResult = await workflow.execute_activity(
            ActivityName.EXECUTE_REMEDIATION,
            plan,
            **get_activity_options(ActivityName.EXECUTE_REMEDIATION),
        )
        await self._audit(incident.workflow_id, "action_executed",
                          exec_result.action_taken)

        # 7. 5분 대기 후 검증 (Workflow timer)
        await workflow.sleep(timedelta(seconds=settings.VERIFY_WAIT_SEC))

        verification: RecoveryVerification = await workflow.execute_activity(
            ActivityName.VERIFY_RECOVERY,
            incident,
            **get_activity_options(ActivityName.VERIFY_RECOVERY),
        )

        # 8. 롤백 필요 시 (Platform Core Activity)
        if verification.needs_rollback:
            await self._audit(incident.workflow_id, "rollback_triggered",
                              verification.reason)
            await workflow.execute_activity(
                ActivityName.EXECUTE_ROLLBACK,
                plan,
                **get_activity_options(ActivityName.EXECUTE_ROLLBACK),
            )
            await self._audit(incident.workflow_id, "workflow_completed", "rolled_back")
            return "rolled_back"

        await self._audit(incident.workflow_id, "workflow_completed", "recovered")
        return "recovered"

    async def _audit(self, workflow_id: str, event_type: str, summary: str) -> None:
        """record_audit_log Common Activity 호출 헬퍼."""
        log = AuditLog(
            workflow_id=workflow_id,
            scenario="aiops",
            event_type=event_type,
            actor="aiops-agent",
            summary=summary,
        )
        await workflow.execute_activity(
            ActivityName.RECORD_AUDIT_LOG,
            log,
            **get_activity_options(ActivityName.RECORD_AUDIT_LOG),
        )
