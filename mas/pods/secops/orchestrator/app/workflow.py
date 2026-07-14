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
import re
from datetime import datetime, timedelta

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
        IncidentGroup,
        RegulationMapping,
        SecurityEvent,
    )
    from workflows.activity_options import ActivityName, get_activity_options
    from .activities import (
        apply_isolation,
        correlate_incident,
        detect_threat,
        generate_compliance_report,
        generate_postmortem_report,
        lookback_user_events,
        map_regulation,
        record_audit_log,
        record_compliance_report,
        record_postmortem_report,
        revoke_iam_privilege,
        send_action_result,
        send_approval_request,
    )
    from .detection import build_incident_group, dedup_events, extract_evidence

# Rule Filter — 권한부여 이벤트 중 LLM(map_regulation) 판단 없이 통과시켜도 되는
# 고위험 관리형 정책 목록(정책 ARN의 마지막 세그먼트로 매칭). 계정 탈취 대응.
_HIGH_RISK_MANAGED_POLICIES = {"AdministratorAccess", "PowerUserAccess", "IAMFullAccess"}
_POLICY_GRANT_EVENTS = ("AttachUserPolicy", "PutUserPolicy", "AttachRolePolicy", "AttachGroupPolicy")
# 대응 분기용 — 이 event_name들은 apply_isolation(CNP) 대신 revoke_iam_privilege(IAM)를 태움.
_IAM_RESPONSE_EVENTS = _POLICY_GRANT_EVENTS + ("CreateAccessKey",)

# Slack Block Kit의 section text는 3000자 제한(넘으면 chat.postMessage가 invalid_blocks로
# 실패 — bot.py의 build_approval_blocks가 이 제한을 진짜로 지키는 마지막 방어선이지만,
# 여기서도 애초에 카드 내용을 짧게 만들어 모바일 가독성까지 같이 챙긴다.
_MAX_EVENTS_IN_CARD = 5
_MAX_SUMMARY_SENTENCES = 3
_MAX_ACTION_LINES = 3


def _parse_trigger_time(evidence: dict, fallback: datetime) -> datetime:
    """lookback 시간창의 기준 시각 — evidence['event_time'](원본 CloudTrail eventTime)을
    우선한다. event.detected_at은 파싱/처리 시각이라 실 이벤트 발생 시각과 어긋날 수 있어
    lookback 창(과거 1시간) 계산에 그대로 쓰면 안 됨. 파싱 실패/누락 시에만 fallback."""
    raw = evidence.get("event_time", "")
    if not raw:
        return fallback
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return fallback


def _rule_filter_skip(evidence: dict) -> bool:
    """저위험 권한부여 이벤트인지 판정 — map_regulation(LLM) 호출을 스킵해도 되면 True.
    순수 함수(I/O 없음) — 단일 이벤트 경로/계정 탈취 그룹 경로 양쪽에서 재사용."""
    event_name = evidence.get("event_name", "")
    policy_arn = evidence.get("policy_arn", "")
    if event_name in _POLICY_GRANT_EVENTS and policy_arn:
        policy_name = policy_arn.rsplit("/", 1)[-1]
        return policy_name not in _HIGH_RISK_MANAGED_POLICIES
    # policy_arn 없음(인라인 정책) 또는 CreateAccessKey/그 외 이벤트 → 보수적으로 통과
    return False


def _dedup_iam_response_events(events: list[SecurityEvent]) -> list[SecurityEvent]:
    """같은 회수 대상(정책 attach/키 생성)이 반복 lookback으로 여러 이벤트에 걸쳐
    중복으로 잡혀도 회수는 한 번만 하도록 첫 등장분만 남긴다.
    detection.py의 dedup_events는 cloudtrail_event_id 기준이라 "같은 정책을 서로
    다른 시각에 두 번 attach"처럼 이벤트 자체는 다른데 실제 회수 대상(같은 유저의
    같은 policy_arn, 또는 같은 access_key_id)은 같은 경우를 못 걸러서 여기서 따로
    거른다. Lambda 쪽 현재상태 확인(list_access_keys 등)과는 별개 — 이건 "같은
    타겟을 여러 번 호출하지 말자"는 워크플로우 단의 중복 제거, 그건 "그 타겟이
    지금도 유효한지" Lambda 단의 최신성 확인."""
    seen: set[tuple] = set()
    deduped: list[SecurityEvent] = []
    for e in events:
        ev = extract_evidence(e)
        name = ev.get("event_name", "")
        if name == "AttachRolePolicy":
            key = (name, ev.get("target_role", ""), ev.get("policy_arn", ""))
        elif name == "CreateAccessKey":
            key = (name, ev.get("access_key_id", ""))
        elif name in _POLICY_GRANT_EVENTS:  # AttachUserPolicy/PutUserPolicy/AttachGroupPolicy
            key = (name, ev.get("target_user", ""), ev.get("policy_arn", ""))
        else:
            key = (name, ev.get("target_user", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    return deduped


def _describe_event_for_card(event_dict: dict) -> str:
    """Slack 카드용 — 이벤트 하나를 사람이 읽는 한 줄 설명으로. event_name만으론
    "AttachUserPolicy" 자체가 뭘 의미하는지 안 드러나서 policy_arn 마지막 세그먼트
    (정책명)까지 보여준다."""
    event_name = event_dict.get("event_name", "")
    policy_arn = event_dict.get("policy_arn", "")
    policy_name = policy_arn.rsplit("/", 1)[-1] if policy_arn else ""

    if event_name == "AttachUserPolicy":
        return f"{policy_name} 부여" if policy_name else "정책 부여"
    if event_name == "AttachRolePolicy":
        return f"{policy_name} 부여(Role)" if policy_name else "정책 부여(Role)"
    if event_name == "PutUserPolicy":
        return "인라인 정책 부여"
    if event_name == "CreateAccessKey":
        return "액세스 키 생성"
    return event_name or "알 수 없음"


def _format_event_time_for_card(event_dict: dict) -> str:
    """카드 표시용 시각 — event_time(원본 CloudTrail eventTime)을 우선 쓴다.
    detected_at(파싱 처리 시각)만 있으면 그걸로 폴백하되, 실제 발생 시각과 다를 수
    있음을 감안해야 한다(_parse_trigger_time과 동일 이유). 마이크로초는 노출하지
    않고 초 단위까지만 자른다."""
    raw = event_dict.get("event_time") or event_dict.get("detected_at") or ""
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return parsed.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return "--:--:--"


def _render_evidence_for_card(evidence: dict) -> str:
    """Slack 카드(1차 승인)에 보여줄 evidence 텍스트. 계정 탈취 Incident 묶음
    (evidence에 "events" 키가 있는 경우)만 전용 포맷으로 사람이 읽게 렌더링하고,
    그 외(단일 이벤트/네트워크 알람 evidence)는 기존처럼 raw key:value 그대로 —
    이번 개선 범위는 보고된 계정 탈취 카드 한정, 다른 시나리오 evidence 모양까지
    새로 설계하지 않는다.
    audit 로그(_audit 호출)는 이 함수를 거치지 않고 mapping.evidence 원본을 그대로
    쓴다 — 카드 표시(사람용)와 감사 기록(기계 판독용)을 분리하기 위함."""
    if "events" not in evidence:
        return (
            "\n".join(f"  {k}: {v}" for k, v in evidence.items())
            if evidence else "  (없음)"
        )

    events = evidence.get("events", [])
    shown_events = events[:_MAX_EVENTS_IN_CARD]
    lines = [f"관련 이벤트 ({len(events)}건):"]
    for idx, event_dict in enumerate(shown_events, start=1):
        time_str = _format_event_time_for_card(event_dict)
        event_name = event_dict.get("event_name", "알 수 없음")
        description = _describe_event_for_card(event_dict)
        lines.append(f"  {idx}. {time_str}  {event_name}  → {description}")
    if len(events) > _MAX_EVENTS_IN_CARD:
        lines.append(f"  … 외 {len(events) - _MAX_EVENTS_IN_CARD}건 (전체는 감사 로그 참고)")

    target_user_arn = evidence.get("target_user_arn", "")
    if target_user_arn:
        lines.append(f"\n대상 계정: {target_user_arn}")

    lines.append(f"lookback 조회: {'실패' if evidence.get('lookback_failed') else '성공'}")

    return "\n".join(lines)


def _source_label(event: SecurityEvent, evidence: dict) -> str:
    """카드 제목(summary)에 쓸 소스(주체) 라벨. event.source_pod는 CloudTrail로 들어온
    IAM 이벤트엔 애초에 값이 없어 "unknown"으로 뜬다(detection.py의 to_security_event
    기본값) — pod 자체가 없는 시나리오라 pod 이름 대신 행위자/대상으로 보여준다.
    네트워크 경로(event_source != "cloudtrail")는 기존처럼 pod 이름 그대로."""
    if event.event_source != "cloudtrail":
        return event.source_pod

    actor_arn = evidence.get("user_arn", "")
    actor = actor_arn.rsplit("/", 1)[-1] if actor_arn else "불명"
    target = evidence.get("target_user", "") or "불명"
    return f"행위자 {actor} → 대상 {target}"


def _wrap_summary_for_card(text: str) -> str:
    """카드에 넣을 긴 서술형 텍스트(causal_summary 등)를 문장(". " 기준) 단위로
    줄바꿈하고, 모바일 가독성 + Slack 3000자 블록 제한을 위해 앞의
    _MAX_SUMMARY_SENTENCES개까지만 보여준다(넘으면 요약 표시 추가). Sonnet 출력/
    프롬프트나 audit 로그(mapping.violation_description 원본)는 안 건드리고
    카드 렌더링 시점에만 축약한다 — 전체 내용이 필요하면 감사 로그를 봐야 함."""
    if not text:
        return text
    sentences = [s.strip() for s in text.split(". ") if s.strip()]
    truncated = len(sentences) > _MAX_SUMMARY_SENTENCES
    shown = sentences[:_MAX_SUMMARY_SENTENCES]
    if truncated:
        lines = [f"{s}." for s in shown]
        lines.append("(요약 — 전체 내용은 감사 로그 참고)")
    else:
        lines = [s if idx == len(shown) - 1 else f"{s}." for idx, s in enumerate(shown)]
    return "\n".join(lines)


_ACCESS_KEY_ID_PATTERN = re.compile(r"AccessKeyId=([A-Z0-9]+)")


def _mask_access_key_ids(text: str) -> str:
    """Slack 카드에 노출되는 AccessKeyId를 앞 4자 + 뒤 4자만 남기고 마스킹
    (AKIA...PHUW → AKIA****PHUW). action_taken 문자열은 activities.py의
    _describe_iam_action(dry-run 설명)과 lambda/secops-iam-responder/handler.py의
    _revoke_iam_privilege(실제 결과)에서 "AccessKeyId=..." 형태로 만들어지는데,
    그 원본 문자열 자체는 안 건드리고 카드에 넣기 직전에만 마스킹한다 — audit
    로그(_audit 호출)는 이 함수를 거치지 않고 action_taken 원본 그대로 남아
    추적 시 전체 값을 볼 수 있다."""
    def _mask(match: re.Match) -> str:
        key_id = match.group(1)
        if len(key_id) <= 8:
            return match.group(0)  # 너무 짧으면 마스킹 의미 없음 — 원본 유지
        return f"AccessKeyId={key_id[:4]}****{key_id[-4:]}"

    return _ACCESS_KEY_ID_PATTERN.sub(_mask, text)


def _summarize_action_taken(action_taken: str) -> str:
    """revoke_iam_privilege/apply_isolation의 action_taken(한 줄 = 이벤트/작업 하나)을
    앞 _MAX_ACTION_LINES줄까지만 보여주고 나머지는 "외 N건"으로 줄인다. 단일 이벤트
    경로(apply_isolation 등)는 원래 한 줄이라 그대로 통과한다."""
    if not action_taken:
        return action_taken
    lines = action_taken.split("\n")
    if len(lines) <= _MAX_ACTION_LINES:
        return action_taken
    shown = lines[:_MAX_ACTION_LINES]
    remaining = len(lines) - _MAX_ACTION_LINES
    return "\n".join(shown) + f"\n… 외 {remaining}건 (전체는 감사 로그 참고)"


def _summarize_iam_actions(events: list[SecurityEvent]) -> str:
    """"정책 회수 N건, 액세스 키 비활성화 M건" 형태의 건수 요약. 성공/실패 여부와
    무관하게 몇 건을 시도했는지만 보여준다(성공/실패 상세는 action_taken 줄에서 확인) —
    activities.py의 action_taken 문자열을 파싱하지 않고 workflow.py가 이미 들고 있는
    iam_response_events를 직접 세어서 ExecutionResult 모델은 그대로 둔다."""
    policy_count = sum(
        1 for e in events if extract_evidence(e).get("event_name", "") in _POLICY_GRANT_EVENTS
    )
    key_count = sum(
        1 for e in events if extract_evidence(e).get("event_name", "") == "CreateAccessKey"
    )
    other_count = len(events) - policy_count - key_count

    parts = []
    if policy_count:
        parts.append(f"정책 회수 {policy_count}건")
    if key_count:
        parts.append(f"액세스 키 비활성화 {key_count}건")
    if other_count:
        parts.append(f"기타 {other_count}건")
    return ", ".join(parts) if parts else "대응 대상 없음"


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

        evidence = extract_evidence(event)
        event_name = evidence.get("event_name", "")
        policy_arn = evidence.get("policy_arn", "")

        # 대응 분기(4번)에서 IAM 회수 대상으로 쓸 이벤트 목록 — 기본값은 트리거 이벤트
        # 하나(기존 단일 이벤트 경로와 동일). 계정 탈취 그룹 경로에서만 Incident에 묶인
        # 이벤트들로 교체된다 — 이래야 대응 분기까지 스코프가 살아남는다(기존엔
        # incident_group/judged_events가 아래 if 블록 지역변수라 여기까지 안 보였음).
        iam_response_events: list[SecurityEvent] = [event]

        # 계정 탈취 트리거 판정 — CreateAccessKey만. Admin 부여(AttachUserPolicy 등)는
        # 더 이상 단독 트리거가 아니라, 아래 lookback이 과거 1시간에서 찾아온다.
        is_account_takeover_trigger = (
            event.event_source == "cloudtrail" and event_name == "CreateAccessKey"
        )

        if is_account_takeover_trigger:
            # 1.5) lookback — target user 과거 1시간 siem.cloudtrail(us-east-1) 조회
            # 창 기준 시각은 반드시 원본 CloudTrail eventTime — event.detected_at(파싱 시각)을
            # 쓰면 처리 지연만큼 창이 뒤로 밀려 과거 이벤트를 놓칠 수 있다.
            trigger_time = _parse_trigger_time(evidence, event.detected_at)
            user_arn_match = re.match(r"^(arn:aws:iam::\d+:)", evidence.get("user_arn", ""))
            account_prefix = user_arn_match.group(1) if user_arn_match else ""
            target_username = evidence.get("target_user", "")
            if target_username and account_prefix:
                target_user_arn = f"{account_prefix}user/{target_username}"
            else:
                # CreateAccessKey에 userName 없이 자기 자신 대상으로 호출된 경우 — 행위자=대상
                target_user_arn = evidence.get("user_arn", "")

            lookback_failed = False
            lookback_events: list[SecurityEvent] = []
            if target_user_arn:
                try:
                    lookback_events = await workflow.execute_activity(
                        lookback_user_events,
                        args=[target_user_arn, trigger_time, event.cluster_name],
                        **get_activity_options(ActivityName.LOOKBACK_USER_EVENTS),
                    )
                except Exception as exc:  # noqa: BLE001 — lookback 실패가 워크플로우를 막으면 안 됨
                    lookback_failed = True
                    await self._audit(event.workflow_id, "lookback_failed", "lookback 조회 실패",
                                      {"error": str(exc), "target_user_arn": target_user_arn})
            else:
                lookback_failed = True

            # dedup 먼저(중복 이벤트에 개별 판정을 두 번 태우지 않기 위해) → Rule Filter로
            # 저위험 이벤트 제외 → 살아남은 이벤트만 개별 판정(Nova→Haiku, map_regulation 재사용)
            deduped_events = dedup_events([event] + lookback_events)
            event_mappings: list[RegulationMapping] = []
            judged_events: list[SecurityEvent] = []
            for grouped_event in deduped_events:
                grouped_evidence = extract_evidence(grouped_event)
                if _rule_filter_skip(grouped_evidence):
                    continue
                judged_events.append(grouped_event)
                event_mapping: RegulationMapping = await workflow.execute_activity(
                    map_regulation, grouped_event,
                    **get_activity_options(ActivityName.MAP_REGULATION),
                )
                event_mappings.append(event_mapping)

            if not event_mappings:
                # 방어 코드: 현재는 CreateAccessKey가 _POLICY_GRANT_EVENTS에 없어
                # _rule_filter_skip이 트리거 이벤트를 절대 스킵하지 않으므로 이 분기는
                # 지금 코드에서 실제로 안 탄다. 다만 트리거 조건이나
                # _POLICY_GRANT_EVENTS 정의가 나중에 바뀌면(개별 판정 종류 추가 등)
                # event_mappings가 비어 trigger_mapping = event_mappings[0]이
                # IndexError로 조용히 깨질 수 있어 미리 가드한다. 인과판정할 개별
                # 판정 자체가 없으므로 Sonnet(correlate_incident) 호출 없이
                # "위반 없음"으로 안전 종료 — 기존 단일 이벤트 Rule Filter 스킵과
                # 동일한 모양의 RegulationMapping을 재사용한다.
                await self._audit(event.workflow_id, "rule_filter_skipped",
                                  "Rule Filter — 계정 탈취 그룹 전체 스킵(비정상)",
                                  {"target_user_arn": target_user_arn, "trigger_event_name": event_name})
                mapping = RegulationMapping(
                    workflow_id=event.workflow_id,
                    violated_regulations=[],
                    violation_description="Rule Filter: 계정 탈취 그룹 전체가 저위험으로 판정되어 스킵",
                    analyzed_at=workflow.now(),
                    severity="low",
                    confidence=0.0,
                )
            else:
                # 묶기 — 같은 target_user_arn + 1시간 창 (judged_events는 이미 dedup됨,
                # build_incident_group의 재적용은 멱등)
                incident_group: IncidentGroup = build_incident_group(
                    workflow_id=event.workflow_id,
                    target_user_arn=target_user_arn or "unknown",
                    events=judged_events,
                    window_start=trigger_time - timedelta(hours=1),
                    window_end=trigger_time,
                )
                incident_group = incident_group.model_copy(update={"lookback_failed": lookback_failed})

                # Sonnet 인과판정 1회
                incident_group = await workflow.execute_activity(
                    correlate_incident, incident_group,
                    **get_activity_options(ActivityName.CORRELATE_INCIDENT),
                )
                await self._audit(event.workflow_id, "analysis_completed", "계정 탈취 인과판정 완료",
                                  {"incident_group": incident_group.model_dump(mode="json")})

                trigger_mapping = event_mappings[0]  # judged_events[0]은 항상 트리거 이벤트
                if incident_group.is_account_takeover:
                    # 대응 분기(4번)용 — Incident에 묶인 이벤트 중 실제 IAM 회수 대상만 추림.
                    # 트리거(CreateAccessKey)는 _IAM_RESPONSE_EVENTS에 항상 포함돼 있어
                    # 필터 결과가 비는 일은 지금 없지만, 그 상수 정의가 나중에 바뀔 수 있어
                    # (앞서 event_mappings[0] 가드와 동일한 이유) 트리거로 폴백해 방어한다.
                    # 반복 lookback으로 같은 회수 대상(같은 정책/같은 키)이 여러 이벤트로
                    # 중복 잡히는 걸 여기서 한 번 걸러 Lambda를 불필요하게 여러 번 안 부른다
                    # (그 타겟이 지금도 유효한지는 Lambda 쪽 현재상태 확인이 별도로 함).
                    iam_response_events = _dedup_iam_response_events([
                        e for e in incident_group.events
                        if extract_evidence(e).get("event_name", "") in _IAM_RESPONSE_EVENTS
                    ]) or [event]
                    all_regs = sorted({r for m in event_mappings for r in m.violated_regulations})
                    # per-event evidence는 딕셔너리 병합(update)하면 같은 키(event_name 등)가
                    # 이벤트끼리 서로 덮어써서 정보가 사라진다 — events 리스트로 각각 보존.
                    merged_evidence: dict = {
                        "incident_event_count": len(incident_group.events),
                        "target_user_arn": incident_group.target_user_arn,
                        "lookback_failed": incident_group.lookback_failed,
                        "events": [
                            {
                                "detected_at": e.detected_at.isoformat(),
                                **{
                                    k: v
                                    for k, v in extract_evidence(e).items()
                                    if k in (
                                        "event_name", "policy_arn", "user_arn",
                                        "target_user", "event_time",
                                    )
                                },
                            }
                            for e in incident_group.events
                        ],
                    }
                    mapping = RegulationMapping(
                        workflow_id=event.workflow_id,
                        violated_regulations=all_regs or ["전자금융감독규정 — 계정 탈취(권한 상승/지속성 확보) 의심"],
                        violation_description=incident_group.causal_summary,
                        blast_radius_safe=trigger_mapping.blast_radius_safe,
                        blast_radius_detail=trigger_mapping.blast_radius_detail,
                        analyzed_at=workflow.now(),  # 결정성 위해 명시 (default_factory=utc_now 회피)
                        severity="critical",
                        confidence=incident_group.correlation_confidence,
                        evidence=merged_evidence,
                    )
                else:
                    mapping = RegulationMapping(
                        workflow_id=event.workflow_id,
                        violated_regulations=[],
                        violation_description=(
                            incident_group.causal_summary or "Sonnet 인과판정: 계정 탈취 아님으로 판단"
                        ),
                        analyzed_at=workflow.now(),
                        severity="low",
                        confidence=incident_group.correlation_confidence,
                        evidence={
                            "incident_event_count": len(incident_group.events),
                            "target_user_arn": incident_group.target_user_arn,
                            "lookback_failed": incident_group.lookback_failed,
                        },
                    )
        elif _rule_filter_skip(evidence):
            # 1.5) Rule Filter — 순수 판정(I/O 없음)만으로 저위험 권한부여 이벤트는
            #      map_regulation(LLM) 호출 없이 스킵.
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
            # 2) 규제 매핑 (RAG + Claude) — Rule Filter 통과분만 LLM 태움
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
        evidence_text = _render_evidence_for_card(mapping.evidence)
        lookback_warning = (
            "⚠️ lookback 조회 실패 — 이 판정은 불완전한 정보(트리거 이벤트만)에 기반합니다.\n\n"
            if mapping.evidence.get("lookback_failed")
            else ""
        )
        # blast_radius_detail은 check_blast_radius(activities.py)가 pod 격리 관점으로만
        # 계산해서 IAM 이벤트(event_source=="cloudtrail")엔 "단일 worker pod(unknown) 격리"
        # 처럼 안 맞는 문구가 나온다. 점수 계산 로직 자체는 그대로 두고(범위 밖), IAM
        # 경로일 때 카드에 보여줄 문구만 IAM 맥락으로 바꾼다. 네트워크 경로는 기존 그대로.
        if event.event_source == "cloudtrail":
            iam_target = (
                mapping.evidence.get("target_user_arn")
                or mapping.evidence.get("target_user")
                or mapping.evidence.get("user_arn")
                or "대상 불명"
            )
            blast_radius_line = f"권한 범위: {iam_target}의 첨부 정책 · 액세스 키 (pod 격리 대상 아님)"
        else:
            blast_radius_line = (
                f"Blast Radius: {'안전' if mapping.blast_radius_safe else '위험'} — "
                f"{mapping.blast_radius_detail}"
            )
        approval_req = ApprovalRequest(
            workflow_id=event.workflow_id,
            scenario="secops",
            severity=mapping.severity,
            summary=f"보안 격리 승인 요청: {_source_label(event, evidence)}",
            detail=(
                f"{lookback_warning}"
                f"[{mapping.severity.upper()}] confidence={mapping.confidence:.0%}\n"
                f"{_wrap_summary_for_card(mapping.violation_description)}\n\n"
                f"Evidence:\n{evidence_text}\n\n"
                f"{blast_radius_line}"
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
        # revoke_iam_privilege는 리스트를 받는다 — 계정 탈취 그룹이면 iam_response_events가
        # Incident에 묶인 회수 대상 전부, 그 외 단일 이벤트 경로면 기본값 [event] 그대로.
        # apply_isolation 쪽은 지금처럼 mapping 하나.
        response_arg = iam_response_events if is_iam_threat else mapping
        # revoke_iam_privilege는 heartbeat 없는 단발성 호출(VPC 밖 IAM 회수 Lambda invoke,
        # secops-iam-responder.tf) — apply_isolation과 옵션(heartbeat_timeout)을 공유하면
        # 안 됨. 각자 맞는 ActivityName으로 분리.
        response_options = get_activity_options(
            ActivityName.REVOKE_IAM_PRIVILEGE if is_iam_threat else ActivityName.APPLY_ISOLATION
        )

        # 5) 1차 승인 → dry-run 검증 → 그 결과를 2차 승인 카드로 재확인 → 승인 시 실제 실행
        dry_run_result = await workflow.execute_activity(
            response_activity, args=[response_arg, True],
            **response_options,
        )
        await self._audit(event.workflow_id, "action_dry_run", "대응 사전 검증",
                          {"result": dry_run_result.model_dump(mode="json")})

        # 대응 건수 요약 — IAM 경로만 의미 있음(네트워크는 pod 1개 격리라 요약 불필요).
        # action_taken은 이벤트/작업당 한 줄이라 줄 수로 안전하게 잘라도 됨(Slack
        # section 3000자 제한 + 모바일 가독성 둘 다 대비).
        action_summary_prefix = f"{_summarize_iam_actions(iam_response_events)}\n" if is_iam_threat else ""
        second_approval_req = ApprovalRequest(
            workflow_id=event.workflow_id,
            scenario="secops",
            severity=mapping.severity,
            summary=f"[2차 승인] 실제 대응 실행 확인: {_source_label(event, evidence)}",
            detail=(
                f"1차 승인 완료. 사전 검증(dry-run) 결과:\n"
                f"{action_summary_prefix}"
                f"{_mask_access_key_ids(_summarize_action_taken(dry_run_result.action_taken))}\n\n"
                f"위 내용이 실제로 적용됩니다. 실행할까요?"
            ),
            regulation_mapping=mapping,
        )
        second_ticket = await workflow.execute_activity(
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
                **response_options,
            )
            await self._audit(event.workflow_id, "action_executed", "대응 실행",
                              {"result": result.model_dump(mode="json")})
            # 실행 결과를 2차 카드 스레드에 통지 (성공/실패/미지원/dry-run-안전망 전부 포함)
            # dry-run 카드와 동일하게 건수 요약 + 줄 수 제한 — send_action_result는
            # blocks 없는 평문이라 Slack 3000자 제한 대상은 아니지만, 모바일 가독성과
            # 카드 일관성을 위해 동일하게 축약한다.
            result_summary_prefix = f"{_summarize_iam_actions(iam_response_events)}\n" if is_iam_threat else ""
            await workflow.execute_activity(
                send_action_result,
                args=[
                    second_ticket,
                    f"대응 실행 결과 — {_source_label(event, evidence)}\n"
                    f"{result_summary_prefix}"
                    f"{_mask_access_key_ids(_summarize_action_taken(result.action_taken))}",
                ],
                task_queue=HITL_TASK_QUEUE,
                **get_activity_options(ActivityName.SEND_ACTION_RESULT),
            )
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
