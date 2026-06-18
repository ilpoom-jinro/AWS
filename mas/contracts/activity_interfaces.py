# 작성자 : 김민수
# 최종 수정일 : 6월 13일
# 계속 수정하면서 진행하겠습니다 ..

"""

Activity 입출력 정의서

목적:
    Agent 팀 간 인터페이스 통일
    Workflow ↔ Activity 계약 고정

담당자:
    FinOps Activities   → 백준호 / 이준영
    AIOps Activities    → 김경한 / 신봉근
    SecOps Activities   → 조다현 / 허상준
    공통 Activities     → 김민수

구현 규칙:
    입출력 타입은 반드시 contracts/models.py의 Pydantic 모델 사용
    Activity 내부에서 LangGraph를 실행할 경우 결과만 반환 (State 외부 노출 금지)
    HTTP 호출 시 timeout=30.0 반드시 명시
    Bedrock 호출 실패 시:
        ThrottlingException → raise (Temporal retry)
        ValidationException → raise ApplicationError(non_retryable=True)

주의:
    이 파일은 Worker 등록 대상이 아님
    @activity.defn 사용 금지
    구현 로직 작성 금지
    Temporal 의존성 없음 (temporalio import 금지)
"""

from __future__ import annotations

from typing import Protocol

from .models import (
    AnomalyReport,
    ApprovalRequest,
    ApprovalTicket,
    AuditLog,
    CollectMetricsInput,
    ComplianceReport,
    DetectIncidentInput,
    DetectThreatInput,
    ExecutionResult,
    GenerateComplianceReportInput,
    IncidentContext,
    MetricsInput,
    RecoveryVerification,
    RegulationMapping,
    RemediationPlan,
    SecurityEvent,
    TerraformPlan,
)


# ---
# FinOps Activities
# ---

class FinOpsActivities(Protocol):

    async def collect_metrics(
        self,
        input: CollectMetricsInput,
    ) -> MetricsInput:
        """
        메트릭 수집
        구현 위치: mas/agents/finops/src/finops/nodes/detector.py
        """
        ...

    async def analyze_anomaly(
        self,
        metrics: MetricsInput,
    ) -> AnomalyReport:
        """
        수집된 메트릭 기반 비용 이상 분석
        구현 위치: mas/agents/finops/src/finops/nodes/analyzer.py
        """
        ...

    async def generate_iac(
        self,
        report: AnomalyReport,
    ) -> TerraformPlan:
        """
        Terraform HCL 생성 + Actor-Critic 검증 (최대 3회 실패 시 Human Review)
        구현 위치: mas/agents/finops/src/finops/nodes/iac_generator.py
        """
        ...

    async def apply_terraform(
        self,
        plan: TerraformPlan,
    ) -> ExecutionResult:
        """
        Terraform Apply 실행

        중요:
            Agent는 Apply 권한이 없어야 함
            실제 배포 권한은 Platform Core만 보유
        구현 위치: mas/workflows/activities/terraform.py
        """
        ...


# ---
# AIOps Activities
# ---

class AIOpsActivities(Protocol):

    async def detect_incident(
        self,
        input: DetectIncidentInput,
    ) -> IncidentContext:
        """
        Kubernetes 장애 탐지

        - CrashLoopBackOff
        - OOMKilled
        - High Latency
        - ImagePullBackOff
        - PendingTimeout
        - Evicted

        구현 위치: mas/agents/aiops/src/aiops/nodes/detector.py
        """
        ...

    async def analyze_root_cause(
        self,
        incident: IncidentContext,
    ) -> AnomalyReport:
        """
        RCA 분석
        구현 위치: mas/agents/aiops/src/aiops/nodes/analyzer.py
        """
        ...

    async def execute_remediation(
        self,
        plan: RemediationPlan,
    ) -> ExecutionResult:
        """
        승인된 복구 방안 실행

        중요:
            Agent는 실행 권한이 없다
            실제 실행 권한은 Platform Core만 보유한다

        주의:
            plan.strategy == "manual" 인 경우 이 Activity를 호출하지 않는다
            Workflow는 request_approval()로 Human Review 단계로 전환해야 한다
        구현 위치: mas/workflows/activities/remediation.py
        """
        ...

    async def verify_recovery(
        self,
        incident: IncidentContext,
    ) -> RecoveryVerification:
        """
        복구 이후 상태 검증
        구현 위치: mas/agents/aiops/src/aiops/nodes/verifier.py
        """
        ...

    async def execute_rollback(
        self,
        plan: RemediationPlan,
    ) -> ExecutionResult:
        """
        이전 상태로 롤백
        구현 위치: mas/agents/aiops/src/aiops/nodes/rollback.py
        """
        ...


# ---
# SecOps Activities
# ---

class SecOpsActivities(Protocol):

    async def detect_threat(
        self,
        input: DetectThreatInput,
    ) -> SecurityEvent:
        """
        VPC Flow Logs / CloudTrail 기반 위협 탐지
        구현 위치: mas/agents/secops/src/secops/nodes/detector.py
        """
        ...

    async def map_regulation(
        self,
        event: SecurityEvent,
    ) -> RegulationMapping:
        """
        금융 규제 매핑
        구현 위치: mas/agents/secops/src/secops/nodes/reg_mapper.py
        """
        ...

    async def apply_isolation(
        self,
        mapping: RegulationMapping,
    ) -> ExecutionResult:
        """
        Istio Policy 적용 및 격리

        중요:
            Agent는 실행 권한이 없다
            실제 실행 권한은 Platform Core만 보유
        구현 위치: mas/workflows/activities/isolation.py
        """
        ...

    async def generate_compliance_report(
        self,
        input: GenerateComplianceReportInput,
    ) -> ComplianceReport:
        """
        금융 규제 대응 보고서 생성
        구현 위치: mas/agents/secops/src/secops/nodes/reporter.py
        """
        ...



# ---
# Common Activities
# ---

class CommonActivities(Protocol):
        
    async def send_approval_request(
        self,
        request: ApprovalRequest,  
    ) -> ApprovalTicket:
        """
        Slack에 승인 요청 메시지 전송. 즉시 반환

        승인 결과 수신 4시간 8시간 로직은 workflow가 signal + wait_condition()으로 처리
        구현 위치: mas/slack-hitl/bot.py
        """
        ...
        
    
    async def send_reminder(
        self,
        ticket: ApprovalTicket,
    ) -> None:
        """
        리마인더 시점에 Slack 메시지 갱신(chat.update) 또는 재알림 전송
        호출 시점은 Workflow가 결정한다 (ApprovalRequest.reminder_after_hours 경과 시)
        구현 위치: mas/slack-hitl/bot.py
        """
        ...

    async def record_audit_log(
        self,
        log: AuditLog,
    ) -> None:
        """
        RDS PostgreSQL(JSONB) 감사 로그 저장
        구현 위치: mas/platform-sdk/src/platform_sdk/audit.py
        """
        ...