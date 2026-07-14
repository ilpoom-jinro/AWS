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
        ApprovalResult,
        AuditLog,
        ComplianceReport,
        DetectThreatInput,
        ExecutionResult,
        GenerateComplianceReportInput,
        GeneratePostMortemReportInput,
        RegulationMapping,
        SecurityEvent,
    )
    from workflows.activity_options import ActivityName, get_activity_options
    from .activities import (
        apply_isolation,
        detect_threat,
        generate_compliance_report,
        generate_postmortem_report,
        map_regulation,
        record_audit_log,
        record_compliance_report,
        record_postmortem_report,
        revoke_iam_privilege,
        send_approval_request,
    )
    from .detection import extract_evidence

# Rule Filter — 권한부여 이벤트 중 LLM(map_regulation) 판단 없이 통과시켜도 되는
# 고위험 관리형 정책 목록(정책 ARN의 마지막 세그먼트로 매칭). 계정 탈취 대응.
_HIGH_RISK_MANAGED_POLICIES = {"AdministratorAccess", "PowerUserAccess", "IAMFullAccess"}
_POLICY_GRANT_EVENTS = ("AttachUserPolicy", "PutUserPolicy", "AttachRolePolicy", "AttachGroupPolicy")
# 대응 분기용 — 이 event_name들은 apply_isolation(CNP) 대신 revoke_iam_privilege(IAM)를 태움.
_IAM_RESPONSE_EVENTS = _POLICY_GRANT_EVENTS + ("CreateAccessKey",)


@workflow.defn
class SecOpsWorkflow:
    def __init__(self) -> None:
        # Slack에서 들어온 사람 결정들. 1차/2차 승인을 인덱스로 구분(0=1차, 1=2차) —
        # bot.py는 매번 같은 "submit_approval" 시그널을 보내므로, 워크플로우가
        # 몇 번째 승인을 기다리는지는 wait_condition의 인덱스 임계값으로 판단한다.
        self._decisions: list[dict] = []

    # --- Slack HITL 봇이 버튼 클릭 시 이 signal을 보냄 ---
    @workflow.signal
    def submit_approval(self, approved: bool, reviewer_id: str, reason: str = "") -> None:
        self._decisions.append({"approved": approved, "reviewer_id": reviewer_id, "reason": reason})

    @workflow.query
    def awaiting_approval(self) -> bool:
        # 1차 결정조차 아직 없는지만 나타냄(2차 대기 여부는 이 query로 구분 안 됨).
        return len(self._decisions) == 0

    @workflow.run
    async def run(self, detect_input: DetectThreatInput) -> ComplianceReport:
        # 1) 탐지
        event: SecurityEvent = await workflow.execute_activity(
            detect_threat, detect_input,
            **get_activity_options(ActivityName.DETECT_THREAT),
        )
        await self._audit(event.workflow_id, "workflow_started", "SecOps 워크플로우 시작",
                          {"input": event.model_dump(mode="json")})

        # 1.5) Rule Filter — 순수 판정(I/O 없음)만으로 저위험 권한부여 이벤트는
        #      map_regulation(LLM) 호출 없이 스킵. 계정 탈취 대응 v1.
        evidence = extract_evidence(event)
        event_name = evidence.get("event_name", "")
        policy_arn = evidence.get("policy_arn", "")

        skip_llm = False
        if event_name in _POLICY_GRANT_EVENTS:
            if policy_arn:
                policy_name = policy_arn.rsplit("/", 1)[-1]
                skip_llm = policy_name not in _HIGH_RISK_MANAGED_POLICIES
            # policy_arn 없음(PutUserPolicy/PutRolePolicy 등 인라인 정책) → 내용 불명,
            # 보수적으로 통과(skip_llm=False 유지)
        # CreateAccessKey 및 그 외 event_name은 skip_llm=False 유지(보수적으로 통과)

        # 2) 규제 매핑 (RAG + Claude) — Rule Filter 통과분만 LLM 태움
        if skip_llm:
            mapping = RegulationMapping(
                workflow_id=event.workflow_id,
                violated_regulations=[],
                violation_description="Rule Filter: 저위험 이벤트로 자동 판정 스킵",
                analyzed_at=workflow.now(),  # 결정성 위해 명시 (default_factory=utc_now 회피)
                severity="low",
                confidence=0.0,
            )
            await self._audit(event.workflow_id, "rule_filter_skipped", "Rule Filter — 저위험 자동 스킵",
                              {"event_name": event_name, "policy_arn": policy_arn})
        else:
            mapping: RegulationMapping = await workflow.execute_activity(
                map_regulation, event,
                **get_activity_options(ActivityName.MAP_REGULATION),
            )
            # NOTE: README는 analysis_completed에 AnomalyReport를 기대하나 SecOps는 RegulationMapping을 씀.
            #       컨트랙트 팀과 협의해 SecOps 전용 키("mapping")를 README에 추가 예정.
            await self._audit(event.workflow_id, "analysis_completed", "규제 매핑 완료",
                              {"mapping": mapping.model_dump(mode="json")})

        # 3) 분기 — 위반 없으면 조치 없이 종료
        if not mapping.violated_regulations:
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken="규정 위반 아님 — 조치 없음",
                executed_at=workflow.now(),
            )
            return await self._finish(event, mapping, result)

        # 위반 있음 — severity 기반 필터: Critical/High만 Slack push (Medium 이하는 View만)
        if mapping.severity not in ("critical", "high"):
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken=f"규정 위반({mapping.severity}) — Slack 알림 생략, View 대시보드로만 기록",
                executed_at=workflow.now(),
            )
            return await self._finish(event, mapping, result)

        # Critical/High → Slack 승인 요청
        evidence_text = (
            "\n".join(f"  {k}: {v}" for k, v in mapping.evidence.items())
            if mapping.evidence else "  (없음)"
        )
        approval_req = ApprovalRequest(
            workflow_id=event.workflow_id,
            scenario="secops",
            severity=mapping.severity,
            summary=f"보안 격리 승인 요청: {event.source_pod}",
            detail=(
                f"[{mapping.severity.upper()}] confidence={mapping.confidence:.0%}\n"
                f"{mapping.violation_description}\n\n"
                f"Evidence:\n{evidence_text}\n\n"
                f"Blast Radius: {'안전' if mapping.blast_radius_safe else '위험'} — "
                f"{mapping.blast_radius_detail}"
            ),
            regulation_mapping=mapping,
        )
        ticket = await workflow.execute_activity(
            send_approval_request, approval_req,
            task_queue=HITL_TASK_QUEUE,
            **get_activity_options(ActivityName.SEND_APPROVAL_REQUEST),
        )
        await self._audit(event.workflow_id, "approval_requested", "Slack 승인 요청 전송",
                          {"request": approval_req.model_dump(mode="json")})

        # 사람 결정을 durable하게 대기 (만료 시각까지). 워커가 죽어도 상태 보존.
        # TODO(다음): reminder_after_hours 경과 시 send_reminder를 race로 호출
        approval_result = await self._wait_for_decision(
            event.workflow_id, 0, approval_req.expire_after_hours,
        )
        if approval_result is None:
            timeout_result = ApprovalResult(
                workflow_id=event.workflow_id, approved=False,
                reviewer_id="system", reason="승인 시간 초과",
                reviewed_at=workflow.now(),
            )
            await self._audit(event.workflow_id, "approval_timeout", "승인 시간 초과",
                              {"result": timeout_result.model_dump(mode="json")})
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken="승인 시간 초과 — 격리 미실행",
                executed_at=workflow.now(),
            )
            return await self._finish(event, mapping, result)

        if not approval_result.approved:
            await self._audit(event.workflow_id, "approval_denied", "거부됨",
                              {"result": approval_result.model_dump(mode="json")})
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken="승인 거부 → 격리 미실행",
                executed_at=workflow.now(),
            )
            return await self._finish(event, mapping, result)

        await self._audit(event.workflow_id, "approval_granted", "승인됨",
                          {"result": approval_result.model_dump(mode="json")})

        if not mapping.blast_radius_safe:
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken="승인됐으나 blast radius 위험 → 자동격리 보류",
                executed_at=workflow.now(),
            )
            return await self._finish(event, mapping, result)

        # 4) 대응 분기 — IAM(권한상승/지속성 확보) 이벤트는 revoke_iam_privilege,
        #    그 외(네트워크 위협)는 기존 apply_isolation(CNP)
        is_iam_threat = event.event_source == "cloudtrail" and event_name in _IAM_RESPONSE_EVENTS
        response_activity = revoke_iam_privilege if is_iam_threat else apply_isolation
        response_arg = event if is_iam_threat else mapping

        # 5) 1차 승인 → dry-run 검증 → 그 결과를 2차 승인 카드로 재확인 → 승인 시 실제 실행
        dry_run_result = await workflow.execute_activity(
            response_activity, args=[response_arg, True],
            **get_activity_options(ActivityName.APPLY_ISOLATION),
        )
        await self._audit(event.workflow_id, "action_dry_run", "대응 사전 검증",
                          {"result": dry_run_result.model_dump(mode="json")})

        second_approval_req = ApprovalRequest(
            workflow_id=event.workflow_id,
            scenario="secops",
            severity=mapping.severity,
            summary=f"[2차 승인] 실제 대응 실행 확인: {event.source_pod}",
            detail=(
                f"1차 승인 완료. 사전 검증(dry-run) 결과:\n{dry_run_result.action_taken}\n\n"
                f"위 내용이 실제로 적용됩니다. 실행할까요?"
            ),
            regulation_mapping=mapping,
        )
        await workflow.execute_activity(
            send_approval_request, second_approval_req,
            task_queue=HITL_TASK_QUEUE,
            **get_activity_options(ActivityName.SEND_APPROVAL_REQUEST),
        )

        second_approval_result = await self._wait_for_decision(
            event.workflow_id, 1, second_approval_req.expire_after_hours,
        )
        if second_approval_result is None:
            second_timeout_result = ApprovalResult(
                workflow_id=event.workflow_id, approved=False,
                reviewer_id="system", reason="2차 승인 시간 초과",
                reviewed_at=workflow.now(),
            )
            await self._audit(event.workflow_id, "approval_timeout", "2차 승인 시간 초과",
                              {"result": second_timeout_result.model_dump(mode="json")})
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken="2차 승인 시간 초과 — 실제 대응 미실행",
                executed_at=workflow.now(),
            )
        elif second_approval_result.approved:
            await self._audit(event.workflow_id, "second_approval_granted", "2차 승인됨",
                              {"result": second_approval_result.model_dump(mode="json")})
            result = await workflow.execute_activity(
                response_activity, args=[response_arg, False],
                **get_activity_options(ActivityName.APPLY_ISOLATION),
            )
            await self._audit(event.workflow_id, "action_executed", "대응 실행",
                              {"result": result.model_dump(mode="json")})
        else:
            await self._audit(event.workflow_id, "approval_denied", "2차 승인 거부됨",
                              {"result": second_approval_result.model_dump(mode="json")})
            result = ExecutionResult(
                workflow_id=event.workflow_id, success=False,
                action_taken="2차 승인 거부 → 실제 대응 미실행",
                executed_at=workflow.now(),
            )

        return await self._finish(event, mapping, result)

    async def _wait_for_decision(
        self, workflow_id: str, index: int, expire_after_hours: int,
    ) -> ApprovalResult | None:
        """index번째(0=1차, 1=2차) 승인 결정을 durable하게 대기.
        타임아웃 시 None(호출자가 타임아웃 처리)."""
        try:
            await workflow.wait_condition(
                lambda: len(self._decisions) > index,
                timeout=timedelta(hours=expire_after_hours),
            )
        except asyncio.TimeoutError:
            return None
        decision = self._decisions[index]
        return ApprovalResult(
            workflow_id=workflow_id,
            approved=decision["approved"],
            reviewer_id=decision["reviewer_id"],
            reason=decision["reason"],
            reviewed_at=workflow.now(),          # 결정성: default_factory 대신 now() 명시
        )

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
        # 보고서 영구 저장 (RDS) — 감사로그와 동일하게 activity 경유
        await workflow.execute_activity(
            record_compliance_report, report,
            **get_activity_options(ActivityName.RECORD_COMPLIANCE_REPORT),
        )

        # Sev1/2(critical/high)만 사후분석(Post-Mortem) 보고서 추가 생성·저장.
        # Medium 이하는 규제 보고서만 남기고 postmortem은 만들지 않는다(운영 노이즈 억제).
        if mapping.severity in ("critical", "high"):
            postmortem = await workflow.execute_activity(
                generate_postmortem_report,
                GeneratePostMortemReportInput(event=event, mapping=mapping, result=result),
                **get_activity_options(ActivityName.GENERATE_POSTMORTEM_REPORT),
            )
            await workflow.execute_activity(
                record_postmortem_report, postmortem,
                **get_activity_options(ActivityName.RECORD_POSTMORTEM_REPORT),
            )
            await self._audit(event.workflow_id, "postmortem_generated",
                              f"Post-Mortem 생성({mapping.severity})",
                              {"action_items": postmortem.action_items})

        await self._audit(event.workflow_id, "workflow_completed", "워크플로우 완료",
                          {"summary": f"{result.action_taken} (격리 적용: {report.isolation_applied})"})
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
