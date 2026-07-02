# 작성자 : 김민수
# 최종 수정일 : 6월 13일
# 계속 수정하면서 진행하겠습니다 ..
# 새 모델 추가 시 저한테 반드시 알려주세요! 아니면 업데이트해주세요~ 그래야 다른 팀원들이 혼란없이 사용할 수 있습니다

from __future__ import annotations

import logging
import warnings
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyAddress,
    model_validator,
)

logger = logging.getLogger(__name__)



# ---
# 공통 상수 / 유틸
# ---

CONTRACT_VERSION = "v1"

def utc_now() -> datetime:
    """Timezone-aware UTC datetime"""
    return datetime.now(UTC)


def new_workflow_id() -> str:
    """
    워크플로우 ID 생성

    예:
        mas:wf-20260608-a1b2c3d4
    """
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    short_uuid = str(uuid4()).split("-")[0]
    return f"mas:wf-{date_str}-{short_uuid}"


# ---
# 공통 타입 정의
# ---

ScenarioType = Literal["finops", "aiops", "secops"]

SeverityType = Literal[
    "critical",
    "high",
    "medium",
    "low",
]

AnomalyType = Literal[
    "over_provisioned",
    "cost_spike",
    "idle_resource",

    "crashloop_backoff",
    "oom_killed",
    "high_latency",
    "image_pull_backoff",
    "pending_timeout",
    "evicted",

    "security_threat",
    "regulation_breach",
]

# ㄹ시나리오 추가 시 이제 PLAN_FIELD_BY_SCENARIO만 수정하시면 됩니다.
PLAN_FIELD_BY_SCENARIO = {
    "finops": "terraform_plan",
    "aiops": "remediation_plan",
    "secops": "regulation_mapping",
}

class ContractVersionMixin(BaseModel):
    """
    모든 계약 모델의 공통 베이스

    contract_version 불일치 시 경고 로그를 남기고 모델 생성은 허용한다 (soft 검증 방식인 이유는 개발 속도를 높이기 위해서)
    버전 불일치를 즉시 중단이 아닌 경고로 처리하는 이유:
        현재는 v1 단일 버전이므로 개발 중 실수를 조용히 잡기 위함
        향후 v2 마이그레이션 시 strict 검증으로 교체를 검토하겠음
    """
    contract_version: str = CONTRACT_VERSION

    @model_validator(mode="before")
    @classmethod
    def warn_version_mismatch(cls, data: Any) -> Any:
        if isinstance(data, dict):
            v = data.get("contract_version", CONTRACT_VERSION)
            if v != CONTRACT_VERSION:
                msg = (
                    f"[{cls.__name__}] contract_version 불일치: "
                    f"수신={v!r}, 현재={CONTRACT_VERSION!r}. "
                    f"contracts/README.md 마이그레이션 가이드를 확인하세요"
                )
                warnings.warn(msg, stacklevel=2)
                logger.warning(
                    "contract_version_mismatch",
                    extra={
                        "model": cls.__name__,
                        "received": v,
                        "expected": CONTRACT_VERSION,
                    },
                )
        return data


class WorkflowRootMixin(ContractVersionMixin):
    """
    워크플로우 진입점 모델 workflow_id를 자동 생성한다

    해당 모델: MetricsInput, IncidentContext, SecurityEvent
    """
    workflow_id: str = Field(default_factory=new_workflow_id)


class WorkflowDerivedMixin(ContractVersionMixin):
    """
    워크플로우 파생 모델 workflow_id를 반드시 상위 모델에서 전달받아야 한다 (일단 이렇게 설계했는데 진행하면서 바뀔 수도 있습니다)

    해당 모델: TerraformPlan, RemediationPlan, RecoveryVerification,
              RegulationMapping, ComplianceReport, AnomalyReport,
              ApprovalRequest, ApprovalResult, AuditLog, ExecutionResult

    주의: workflow_id를 직접 생성(new_workflow_id())하지 않는다
    """
    workflow_id: str


# ---
# FinOps
# ---

class MetricsInput(WorkflowRootMixin):
    collected_at: datetime = Field(default_factory=utc_now)
    cluster_name: str
    namespace: str
    resource_name: str

    source: Literal[
        "prometheus",
        "kubecost",
        "billing_api",
    ]

    cpu_usage_avg_7d: float = Field(
        ge=0.0,
        le=1.0,
    )

    memory_usage_avg_7d: float = Field(
        ge=0.0,
        le=1.0,
    )

    cpu_request: float = Field(
        ge=0.0,
    )

    memory_request_gb: float = Field(
        ge=0.0,
    )

    cost_per_day_usd: float = Field(
        ge=0.0,
    )

    cost_per_month_usd: float = Field(
        ge=0.0,
    )


class TerraformPlan(WorkflowDerivedMixin):
    generated_at: datetime = Field(default_factory=utc_now)
    hcl_content: str
    validation_passed: bool = False

    validation_attempts: int = Field(
        default=0,
        ge=0,
        le=3,
    )

    validation_errors: list[str] = Field(default_factory=list)
    estimated_cost_delta_usd: float = 0.0
    rollback_plan: str = ""


# ---
# AIOps
# ---

class IncidentContext(WorkflowRootMixin):
    detected_at: datetime = Field(default_factory=utc_now)
    cluster_name: str
    namespace: str
    pod_name: str

    anomaly_type: Literal[
        "crashloop_backoff",
        "oom_killed",
        "high_latency",
        "image_pull_backoff",
        "pending_timeout",
        "evicted",
    ]

    restart_count: int = Field(
        default=0,
        ge=0,
    )

    cpu_usage_current: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    memory_usage_current: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    error_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    recent_logs: list[str] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "최근 로그 최대 50줄 (일단 임의로 제가 제한걸었습니다 나중에 작업하시다가 수정이 필요해지면 말씀해주세요) "
            "Temporal Event History 단일 payload 2MB 제한 대응 "
            "전체 로그는 loki / S3 / CloudWatch Logs 등 외부 저장소를 사용할 것"
        ),
    )


class RemediationPlan(WorkflowDerivedMixin):
    root_cause: str

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    strategy: Literal[
        "restart",
        "scale_out",
        "rollback",
        "manual",
    ]

    strategy_detail: str

    estimated_recovery_minutes: int = Field(
        default=5,
        ge=0,
    )

    previous_image: str = ""
    rollback_available: bool = False

    # ── Platform Core 실행 지원 필드 ────────────────────────────────────────
    # AIOps Workflow가 IncidentContext에서 채워서 전달한다.

    # restart / rollback strategy 전용: Deployment 이름을 직접 지정하는 대신
    # pod_name 으로 Platform Core가 kubectl을 통해 Deployment를 추론한다.
    # (요청서 §2: "pod_name에서 Deployment를 추론")
    pod_name: str = ""

    # scale_out rollback 전용: execute_remediation 이 HPA 패치 직전 maxReplicas 를
    # ExecutionResult.output 으로 반환하면, AIOps Workflow가 이 필드에 저장한 뒤
    # execute_rollback 에 넘긴다. 0이면 미설정(delta 차감 방식으로 폴백).
    previous_hpa_max_replicas: int = 0


class RecoveryVerification(WorkflowDerivedMixin):
    verified_at: datetime = Field(default_factory=utc_now)
    recovered: bool
    needs_rollback: bool

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    reason: str = ""


# ---
# SecOps
# ---

class SecurityEvent(WorkflowRootMixin):
    detected_at: datetime = Field(default_factory=utc_now)
    cluster_name: str
    namespace: str
    source_pod: str
    source_ip: IPvAnyAddress
    destination_ip: IPvAnyAddress

    destination_port: int = Field(
        ge=1,
        le=65535,
    )

    protocol: Literal[
        "tcp",
        "udp",
        "icmp",
    ]

    direction: Literal[
        "inbound",
        "outbound",
    ]

    threat_type: Literal[
        "abnormal_outbound",
        "port_scan",
        "data_exfiltration",
        "policy_violation",
    ]

    raw_log: str = ""


class RegulationMapping(WorkflowDerivedMixin):
    analyzed_at: datetime = Field(default_factory=utc_now)
    violated_regulations: list[str]
    violation_description: str
    blast_radius_safe: bool = False
    blast_radius_detail: str = ""
    isolation_policy_yaml: str = ""


class ComplianceReport(WorkflowDerivedMixin):
    generated_at: datetime = Field(default_factory=utc_now)
    severity: SeverityType
    violated_regulations: list[str]
    threat_summary: str
    action_taken: str
    isolation_applied: bool


# ---
# 공통 분석 결과
# ---

class AnomalyReport(WorkflowDerivedMixin):
    scenario: ScenarioType
    analyzed_at: datetime = Field(default_factory=utc_now)
    anomaly_type: AnomalyType
    severity: SeverityType
    affected_resource: str
    summary: str
    detail: str

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    terraform_plan: TerraformPlan | None = None
    remediation_plan: RemediationPlan | None = None
    regulation_mapping: RegulationMapping | None = None
    estimated_savings_usd: float = 0.0

    @model_validator(mode="after")
    def check_scenario_plan_consistency(self) -> "AnomalyReport":
        """
        scenario와 첨부 플랜의 일관성을 검증한다

        규칙:
            플랜이 있는데 시나리오가 맞지 않으면 ValueError 발생
            플랜이 없는 경우는 허용한다 (분석 단계에서 플랜 없이 보고서만 생성하는 케이스)

        허용 조합:
            finops  → terraform_plan (O),  remediation_plan (X), regulation_mapping (X)
            aiops   → terraform_plan (X),  remediation_plan (O), regulation_mapping (X)
            secops  → terraform_plan (X),  remediation_plan (X), regulation_mapping (O)
        """
        allowed = PLAN_FIELD_BY_SCENARIO.get(self.scenario)
        for field_name in PLAN_FIELD_BY_SCENARIO.values():
            if field_name != allowed and getattr(self, field_name) is not None:
                raise ValueError(
                    f"AnomalyReport.scenario={self.scenario!r}인데 "
                    f"{field_name!r}이 채워져 있습니다 "
                    f"시나리오와 플랜이 불일치합니다"
                ) 
        return self


# ---
# Slack HITL
# ---

class ApprovalRequest(WorkflowDerivedMixin):
    scenario: ScenarioType
    severity: SeverityType
    summary: str
    detail: str

    reminder_after_hours: int = Field(
        default=4,
        ge=1,
    )

    expire_after_hours: int = Field(
        default=8,
        ge=1,
    )

    terraform_plan: TerraformPlan | None = None
    remediation_plan: RemediationPlan | None = None
    regulation_mapping: RegulationMapping | None = None

    @model_validator(mode="after")
    def validate_plan_consistency(self) -> "ApprovalRequest":
        scenario_mapping = {
            "finops": "terraform_plan",
            "aiops": "remediation_plan",
            "secops": "regulation_mapping",
        }
        target_field = PLAN_FIELD_BY_SCENARIO[self.scenario]
        for field_name in PLAN_FIELD_BY_SCENARIO.values():
            field_value = getattr(self, field_name)
            if field_name == target_field:
                if field_value is None:
                    raise ValueError(
                        f"ApprovalRequest.scenario={self.scenario!r}일 때 "
                        f"{field_name!r}은 필수입니다."
                    )
            else:
                if field_value is not None:
                    raise ValueError(
                        f"ApprovalRequest.scenario={self.scenario!r}인데 "
                        f"{field_name!r}이 채워져 있습니다."
                    )
        for field_name in scenario_mapping.values():
            field_value = getattr(self, field_name)
            if field_name == target_field:
                if field_value is None:
                    raise ValueError(
                        f"ApprovalRequest.scenario={self.scenario!r}일 때 "
                        f"{field_name!r}은 필수입니다."
                    )
            else:
                if field_value is not None:
                    raise ValueError(
                        f"ApprovalRequest.scenario={self.scenario!r}인데 "
                        f"{field_name!r}이 채워져 있습니다."
                    )
        return self


class ApprovalResult(WorkflowDerivedMixin):
    approved: bool
    reviewed_at: datetime = Field(default_factory=utc_now)
    reviewer_id: str
    reviewer_name: str = ""
    reason: str = ""


# ---
# 감사 로그 (계속 수정될 예정..바쁘다 바빠)
# ---

class AuditLog(WorkflowDerivedMixin):
    scenario: ScenarioType
    event_type: Literal[
        "workflow_started",
        "anomaly_detected",
        "analysis_completed",
        "iac_generated",
        "approval_requested",
        "approval_granted",
        "approval_denied",
        "approval_timeout",
        "action_executed",
        "rollback_triggered",
        "workflow_completed",
        "workflow_failed",
    ]

    occurred_at: datetime = Field(default_factory=utc_now)
    actor: str
    summary: str
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="event_type별 payload 구조는 contracts/README.md 참고해주십셔",
    )

# ---
# 실행 결과
# ---

class ExecutionResult(WorkflowDerivedMixin):
    success: bool
    executed_at: datetime = Field(default_factory=utc_now)
    action_taken: str
    output: str = ""
    error: str = ""
    rollback_available: bool = True

# ---
# Activity Input 모델
# ---
#
# 목적:
#   탐지/수집 Activity는 Prometheus, Kubecost, CloudTrail 등을 호출해서 데이터를 만들어내는 진입점
#   입력이 이미 완성된 도메인 모델이면 "어디서 만들어서 넘겨야 하나?"라는 혼란이 생김 그래서 보완한게 식별자 파라미터만 담는 전용 Input 모델을 사용하는 것
#
# Temporal 직렬화:
#   Temporal PayloadConverter이 Pydantic 모델을 기본적으로 지원함
#   ContractVersionMixin을 상속하므로 버전 soft 검증도 자동 적용됨
#
# 분리 기준:
#   models.py가 코드가 너무 길어지거나 (약 700줄 정도?) 충돌이 발생하면 finops_models.py / aiops_models.py / secops_models.py로 분리한다
#   contracts/README.md 참고하기

class CollectMetricsInput(ContractVersionMixin):
    """
    FinOps: Prometheus + Kubecost 메트릭 수집 Activity 입력
    구현 위치: mas/agents/finops/src/finops/nodes/detector.py
    """
    cluster_name: str
    namespace: str
 
 
class DetectIncidentInput(ContractVersionMixin):
    """
    AIOps: Kubernetes 장애 탐지 Activity 입력

    지원 장애 유형:
    - CrashLoopBackOff
    - OOMKilled
    - High Latency
    - ImagePullBackOff
    - PendingTimeout
    - Evicted

    구현 위치: mas/agents/aiops/src/aiops/nodes/detector.py
    """
    cluster_name: str
    namespace: str
 
 
class DetectThreatInput(ContractVersionMixin):
    """
    SecOps: VPC Flow Logs / CloudTrail 기반 위협 탐지 Activity 입력
 
    note:
        SecurityEvent에는 namespace 필드가 있으나
        VPC 레벨 탐지는 namespace 단위가 아닌 vpc_id 단위로 수행된다 탐지 후 SecurityEvent.namespace는 구현체에서 채운다
    구현 위치: mas/agents/secops/src/secops/nodes/detector.py
    """
    cluster_name: str
    vpc_id: str
 
 
class GenerateComplianceReportInput(ContractVersionMixin):
    """
    SecOps: 규제 보고서 생성 Activity 입력
 
    note:
        Temporal 공식 문서 → 복수 파라미터 대신 단일 모델을 권장함
        event / mapping / result 3개를 하나로 묶는다
    구현 위치: mas/agents/secops/src/secops/nodes/reporter.py
    """
    event: SecurityEvent
    mapping: RegulationMapping
    result: ExecutionResult

class ApprovalTicket(WorkflowDerivedMixin):
    """
    Slack HITL 승인 요청 생성 후 반환되는 티켓

    - Slack 메시지 식별
    - 리마인더 전송
    - 메시지 상태 업데이트
    - 승인/거부 결과 반영 용도임
    """
    slack_message_ts: str
    channel_id: str


# ---
# FinOps agent collaboration contracts
# ---

class AgentStatus(str, Enum):
    COMPLETED = "completed"
    NEEDS_DATA = "needs_data"
    BLOCKED = "blocked"
    REQUIRES_REVIEW = "requires_review"
    FAILED = "failed"


class FinOpsAgentContract(BaseModel):
    """Strict base model for messages exchanged by FinOps agents."""

    model_config = ConfigDict(extra="forbid")


class DataRequest(FinOpsAgentContract):
    target_agent: str
    operation: str
    parameters: dict[str, Any]
    required_fields: list[str]
    reason: str


class AgentTask(FinOpsAgentContract):
    workflow_id: str
    agent_key: str
    agent_name: str
    objective: str
    context: dict[str, Any]
    parameters: dict[str, Any]
    requested_fields: list[str]


class AgentResponse(FinOpsAgentContract):
    status: AgentStatus
    agent_key: str
    agent_name: str
    result: dict[str, Any]
    message: str
    evidence: list[str]
    data_requests: list[DataRequest]
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str]
    reasoning_source: Literal["rule", "llm", "rule+llm"]

    @model_validator(mode="after")
    def validate_status_payload(self) -> "AgentResponse":
        if self.status == AgentStatus.NEEDS_DATA and not self.data_requests:
            raise ValueError("needs_data responses must include at least one data request")
        if self.status == AgentStatus.COMPLETED and not self.result:
            raise ValueError("completed responses must include a non-empty result")
        return self


class PlanCandidate(FinOpsAgentContract):
    label: str
    push_window_minutes: int = Field(gt=0)
    required_pods: int = Field(gt=0)
    estimated_cost_usd: float = Field(ge=0.0)
    estimated_p95_ms: float = Field(ge=0.0)
    risk_level: Literal["low", "medium", "high"]
    budget_exceeded: bool
    policy_violations: list[str]
    score: float = 0.0


VALID_FINOPS_AGENT_KEYS = {
    "business_control",
    "demand_shaping",
    "traffic_forecast",
    "bottleneck_capacity",
    "infra_execution",
    "cost",
    "unit_economics",
    "policy_guardrail",
    "observer",
    "fallback",
    "postmortem_learning",
}


AGENT_ALLOWED_REQUESTS: dict[str, list[str]] = {
    "bottleneck_capacity": ["traffic_forecast"],
    "cost": ["infra_execution"],
    "policy_guardrail": ["cost", "unit_economics"],
    "observer": ["traffic_forecast"],
}


class ReplanIntent(FinOpsAgentContract):
    intent: Literal["replan", "query", "partial_replan", "explain"]
    constraints: dict[str, Any]
    forbidden_actions: list[str]
    replan_from: str
    target_agent: str | None = None
    requires_confirmation: bool
    reason: str

    @model_validator(mode="after")
    def validate_replan_from(self) -> "ReplanIntent":
        if self.replan_from not in VALID_FINOPS_AGENT_KEYS:
            raise ValueError(f"unknown replan_from agent_key: {self.replan_from}")
        if self.target_agent is not None and self.target_agent not in VALID_FINOPS_AGENT_KEYS:
            raise ValueError(f"unknown target_agent agent_key: {self.target_agent}")
        return self


class ExecutionMode(str, Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


class ExecutionStepType(str, Enum):
    SCALE_OUT = "scale_out"
    CACHE_PREWARM = "cache_prewarm"
    PUSH_SCHEDULE = "push_schedule"
    VERIFY_READY = "verify_ready"
    GO_NO_GO = "go_no_go"
    SCALE_DOWN_WATCH = "scale_down_watch"


class ExecutionStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionStep(FinOpsAgentContract):
    step_id: str
    step_type: ExecutionStepType
    scheduled_at: str
    parameters: dict[str, Any]
    status: ExecutionStepStatus = ExecutionStepStatus.PENDING
    result: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class ExecutionPlan(FinOpsAgentContract):
    planning_workflow_id: str
    execution_workflow_id: str
    event_id: str
    mode: ExecutionMode
    steps: list[ExecutionStep]
    overall_status: str = "pending"
    created_at: str
    completed_at: str | None = None
