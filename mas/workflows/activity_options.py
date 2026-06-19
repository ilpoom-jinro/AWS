# 작성자 : 김민수
# 최종 수정일 : 6월 18일

"""
Temporal ActivityOptions

위치:
    mas/workflows/activity_options.py

원칙:
    contracts 레이어는 Temporal을 모른다
    Timeout / RetryPolicy 는 workflows 레이어에서 관리한다
    Activity는 재실행 가능(Idempotent)하도록 구현한다
    재시도는 Temporal에 위임하되 무한 재시도는 방지한다

상태 변경 Activity 주의:
    apply_terraform, apply_isolation, execute_remediation, execute_rollback
    이 4개는 RetryPolicy로 중복 실행을 막지 않는다
    중복 실행 방지는 Activity 구현체의 멱등성(Idempotency)으로 해결한다
    같은 4개는 heartbeat_timeout을 가진다
    Worker 장애 시 start_to_close_timeout 전체를 기다리지 않고 감지하기 위함이다
    구현체는 activity.heartbeat()를 주기적으로 호출해야 한다

non_retryable_error_types 미사용 이유:
    contracts/activity_interfaces.py 구현 규칙에 따라
    Bedrock ValidationException 등은 raise 시점에
    ApplicationError(non_retryable=True)를 직접 지정한다
    RetryPolicy.non_retryable_error_types로 타입 문자열을 중앙 관리하면
    위 패턴과 중복/충돌하므로 의도적으로 사용하지 않는다

maximum_attempts=10과 schedule_to_close_timeout 관계 주의:
    DEFAULT_RETRY_POLICY.maximum_attempts=10은 전체 Activity 공통이다
    
    maximum_interval=60s 기준으로 attempt 2~10 사이의 대기 시간을 누적하면 ↓
    1 + 2 + 4 + 8 + 16 + 32 + 60 + 60 + 60 = 243초 (약 4분)

    RECORD_AUDIT_LOG처럼 schedule_to_close_timeout이 짧은 Activity는
    순수 backoff 대기 시간만으로도 budget을 초과하여
    실제로는 7~8회 안팎에서 종료될 수 있다

    반대로 APPLY_TERRAFORM, GENERATE_IAC처럼
    schedule_to_close_timeout이 긴 Activity는
    10회에 더 가깝게 재시도될 수 있다

    단, 실제 실행 시간까지 포함하면
    schedule_to_close_timeout이 먼저 만료될 수 있다
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import NotRequired, TypedDict

from temporalio.common import RetryPolicy

__all__ = [
    "ActivityName",
    "ActivityOptions",
    "DEFAULT_RETRY_POLICY",
    "get_activity_options",
    "get_all_activity_options",
]


# ---
# Activity Names
# ---

class ActivityName(StrEnum):

    # --------------------------------------------------------
    # FinOps
    # --------------------------------------------------------

    COLLECT_METRICS = "collect_metrics"
    ANALYZE_ANOMALY = "analyze_anomaly"
    GENERATE_IAC = "generate_iac"
    APPLY_TERRAFORM = "apply_terraform"

    # --------------------------------------------------------
    # AIOps
    # --------------------------------------------------------

    DETECT_INCIDENT = "detect_incident"
    ANALYZE_ROOT_CAUSE = "analyze_root_cause"
    EXECUTE_REMEDIATION = "execute_remediation"
    VERIFY_RECOVERY = "verify_recovery"
    EXECUTE_ROLLBACK = "execute_rollback"

    # --------------------------------------------------------
    # SecOps
    # --------------------------------------------------------

    DETECT_THREAT = "detect_threat"
    MAP_REGULATION = "map_regulation"
    APPLY_ISOLATION = "apply_isolation"
    GENERATE_COMPLIANCE_REPORT = "generate_compliance_report"

    # --------------------------------------------------------
    # Common
    # --------------------------------------------------------

    SEND_APPROVAL_REQUEST = "send_approval_request"
    SEND_REMINDER = "send_reminder"
    RECORD_AUDIT_LOG = "record_audit_log"


# ---
# Timeout Configuration
# ---

class ActivityTimeoutConfig(TypedDict):
    start_to_close_timeout: timedelta
    schedule_to_close_timeout: timedelta

    # 상태 변경 Activity(apply_terraform 등)만 명시한다
    # 짧은 조회/알림성 Activity는 생략해도 된다
    heartbeat_timeout: NotRequired[timedelta]


ACTIVITY_TIMEOUTS: dict[
    ActivityName,
    ActivityTimeoutConfig,
] = {
    # --------------------------------------------------------
    # FinOps
    # --------------------------------------------------------

    ActivityName.COLLECT_METRICS: {
        "start_to_close_timeout": timedelta(minutes=1),
        "schedule_to_close_timeout": timedelta(minutes=5),
    },

    ActivityName.ANALYZE_ANOMALY: {
        "start_to_close_timeout": timedelta(minutes=3),
        "schedule_to_close_timeout": timedelta(minutes=10),
    },

    # Actor-Critic 검증 루프 (최대 3회 + terraform validate) 포함
    ActivityName.GENERATE_IAC: {
        "start_to_close_timeout": timedelta(minutes=8),
        "schedule_to_close_timeout": timedelta(minutes=25),
    },

    ActivityName.APPLY_TERRAFORM: {
        "start_to_close_timeout": timedelta(minutes=10),
        "schedule_to_close_timeout": timedelta(minutes=30),
        "heartbeat_timeout": timedelta(minutes=1),
    },

    # --------------------------------------------------------
    # AIOps
    # --------------------------------------------------------

    ActivityName.DETECT_INCIDENT: {
        "start_to_close_timeout": timedelta(minutes=1),
        "schedule_to_close_timeout": timedelta(minutes=3),
    },

    ActivityName.ANALYZE_ROOT_CAUSE: {
        "start_to_close_timeout": timedelta(minutes=3),
        "schedule_to_close_timeout": timedelta(minutes=10),
    },

    ActivityName.EXECUTE_REMEDIATION: {
        "start_to_close_timeout": timedelta(minutes=3),
        "schedule_to_close_timeout": timedelta(minutes=10),
        "heartbeat_timeout": timedelta(seconds=30),
    },

    ActivityName.VERIFY_RECOVERY: {
        "start_to_close_timeout": timedelta(minutes=2),
        "schedule_to_close_timeout": timedelta(minutes=10),
    },

    ActivityName.EXECUTE_ROLLBACK: {
        "start_to_close_timeout": timedelta(minutes=2),
        "schedule_to_close_timeout": timedelta(minutes=5),
        "heartbeat_timeout": timedelta(seconds=30),
    },

    # --------------------------------------------------------
    # SecOps
    # --------------------------------------------------------

    ActivityName.DETECT_THREAT: {
        "start_to_close_timeout": timedelta(minutes=1),
        "schedule_to_close_timeout": timedelta(minutes=5),
    },

    ActivityName.MAP_REGULATION: {
        "start_to_close_timeout": timedelta(minutes=2),
        "schedule_to_close_timeout": timedelta(minutes=10),
    },

    ActivityName.APPLY_ISOLATION: {
        "start_to_close_timeout": timedelta(minutes=2),
        "schedule_to_close_timeout": timedelta(minutes=5),
        "heartbeat_timeout": timedelta(seconds=30),
    },

    ActivityName.GENERATE_COMPLIANCE_REPORT: {
        "start_to_close_timeout": timedelta(minutes=2),
        "schedule_to_close_timeout": timedelta(minutes=5),
    },

    # --------------------------------------------------------
    # Common
    # --------------------------------------------------------

    ActivityName.SEND_APPROVAL_REQUEST: {
        "start_to_close_timeout": timedelta(seconds=10),
        "schedule_to_close_timeout": timedelta(seconds=30),
    },

    ActivityName.SEND_REMINDER: {
        "start_to_close_timeout": timedelta(seconds=10),
        "schedule_to_close_timeout": timedelta(seconds=30),
    },

    ActivityName.RECORD_AUDIT_LOG: {
        "start_to_close_timeout": timedelta(seconds=30),
        "schedule_to_close_timeout": timedelta(minutes=2),
    },
}


# ---
# Drift Guard
# ---

if set(ActivityName) != set(ACTIVITY_TIMEOUTS):
    raise RuntimeError(
        "ActivityName과 ACTIVITY_TIMEOUTS가 일치하지 않음 "
        "둘 다 확인할 것"
    )


# ---
# Retry Policy
# ---

DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=10,
)


# ---
# Public Types
# ---

class ActivityOptions(ActivityTimeoutConfig):
    retry_policy: RetryPolicy

# ---
# Public API
# ---

def get_activity_options(
    activity: ActivityName,
    retry_policy: RetryPolicy | None = None,
) -> ActivityOptions:
    """
    Temporal execute_activity() 옵션 반환

    예시:

        await workflow.execute_activity(
            collect_metrics,
            request,
            **get_activity_options(
                ActivityName.COLLECT_METRICS
            ),
        )

        # heartbeat가 설정된 Activity (예: apply_terraform)는
        # 구현체에서 주기적으로 activity.heartbeat()를 호출해야 함
    """

    timeout_config = ACTIVITY_TIMEOUTS[activity]

    options: ActivityOptions = {
        "start_to_close_timeout":
            timeout_config["start_to_close_timeout"],

        "schedule_to_close_timeout":
            timeout_config["schedule_to_close_timeout"],

        "retry_policy":
            retry_policy or DEFAULT_RETRY_POLICY,
    }

    if "heartbeat_timeout" in timeout_config:
        options["heartbeat_timeout"] = timeout_config["heartbeat_timeout"]

    return options


def get_all_activity_options() -> dict[
    ActivityName,
    ActivityOptions,
]:
    """
    디버깅 / 문서화 용도
    """

    return {
        activity: get_activity_options(activity)
        for activity in ActivityName
    }