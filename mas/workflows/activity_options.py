# 작성자 : 김민수
# 최종 수정일 : 6월 13일
# 계속 수정하면서 진행하겠습니다 ..

"""
Activity Options 헬퍼
=====================

Temporal ActivityOptions를 생성하는 유틸리티

위치:
    mas/workflows/activity_options.py

레이어 구조:
    contracts ──────────────────────── (temporalio 의존성 없음, 순수 계약)
        ↑
    workflows/activity_options.py ──── (temporalio 의존성 있음, 실행 정책)
        ↑
    workflows/*.py

ACTIVITY_TIMEOUTS 이전 이유:
    timeout은 입출력 계약이 아닌 Workflow 실행 정책
    contracts는 순수 계약 레이어로 유지

사용법:
    from workflows.activity_options import get_activity_options

    result = await workflow.execute_activity(
        "collect_metrics",
        CollectMetricsInput(cluster_name="eks-prod", namespace="finops"),
        **get_activity_options("collect_metrics"),
    )
"""

from __future__ import annotations

from datetime import timedelta
from typing import TypedDict

from temporalio.common import RetryPolicy


# ============================================================
# Activity Timeout 정책
#
# contracts/activity_interfaces.py에서 이전
# timeout은 입출력 계약이 아닌 Workflow 실행 정책이므로
# workflows 레이어에서 관리
#
# timeout 종류 및 선택 기준은 README.md 참고
# ============================================================

ACTIVITY_TIMEOUTS: dict[str, timedelta] = {
    # FinOps
    "collect_metrics":            timedelta(minutes=5),
    "analyze_anomaly":            timedelta(minutes=10),
    "generate_iac":               timedelta(minutes=20),
    "apply_terraform":            timedelta(minutes=30),
    # AIOps
    "detect_incident":            timedelta(minutes=3),
    "analyze_root_cause":         timedelta(minutes=10),
    "execute_remediation":        timedelta(minutes=10),
    "verify_recovery":            timedelta(minutes=10),
    "execute_rollback":           timedelta(minutes=5),
    # SecOps
    "detect_threat":              timedelta(minutes=5),
    "map_regulation":             timedelta(minutes=10),
    "apply_isolation":            timedelta(minutes=5),
    "generate_compliance_report": timedelta(minutes=5),
    # Common
    "request_approval":           timedelta(hours=8),
    "record_audit_log":           timedelta(minutes=2),
}


# ============================================================
# RetryPolicy 상수 정의
#
# Temporal 기본값:
#   initial_interval:     1초
#   backoff_coefficient:  2.0 (지수 백오프)
#   maximum_attempts:     0 (무제한)
#
# MAS 기본값 (DEFAULT_RETRY_POLICY):
#   maximum_attempts: 3 — 무한 재시도 방지 목적
#
# non_retryable_error_types 설정 방법은 README.md 참고
# ============================================================

DEFAULT_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
)

# HITL Activity 전용 RetryPolicy
# 사람이 직접 검토·승인하는 액션이므로 재시도 없음
# 8시간 타임아웃(request_approval) 내 미응답 시 Workflow 자체 처리
# 타임아웃 만료 후 처리 흐름은 README.md 참고
HITL_RETRY_POLICY = RetryPolicy(
    maximum_attempts=1,
)

# 실행 권한 Activity 전용 RetryPolicy
# 대상: apply_terraform, apply_isolation, execute_remediation, execute_rollback
# 멱등성 미보장 액션의 중복 실행 방지 목적으로 1회만 시도
# 멱등성 보장이 필요한 경우 구현체에서 직접 처리 — README.md 참고
EXECUTION_RETRY_POLICY = RetryPolicy(
    maximum_attempts=1,
)

# Activity별 RetryPolicy 오버라이드 테이블
# DEFAULT_RETRY_POLICY와 다른 Activity만 명시
# get_activity_options() 호출 시 retry_policy 인자로 런타임 오버라이드 가능
_ACTIVITY_RETRY_OVERRIDES: dict[str, RetryPolicy] = {
    "request_approval":    HITL_RETRY_POLICY,
    "apply_terraform":     EXECUTION_RETRY_POLICY,
    "apply_isolation":     EXECUTION_RETRY_POLICY,
    "execute_remediation": EXECUTION_RETRY_POLICY,
    "execute_rollback":    EXECUTION_RETRY_POLICY,
}


class ActivityOption(TypedDict):
    start_to_close_timeout: timedelta
    retry_policy: RetryPolicy


def get_activity_options(
    name: str,
    retry_policy: RetryPolicy | None = None,
) -> ActivityOption:
    """
    Activity 이름으로 Temporal execute_activity() 옵션 딕셔너리 반환

    Workflow execute_activity() 호출 시 ** 언패킹으로 사용

    예시:
        # 기본 사용
        result = await workflow.execute_activity(
            "collect_metrics",
            CollectMetricsInput(cluster_name="eks-prod", namespace="finops"),
            **get_activity_options("collect_metrics"),
        )

        # RetryPolicy 런타임 오버라이드
        result = await workflow.execute_activity(
            "analyze_anomaly",
            metrics,
            **get_activity_options(
                "analyze_anomaly",
                retry_policy=RetryPolicy(maximum_attempts=5),
            ),
        )

    RetryPolicy 우선순위 (높은 순):
        1. retry_policy 인자 (런타임 오버라이드)
        2. _ACTIVITY_RETRY_OVERRIDES 테이블 (Activity별 기본값)
        3. DEFAULT_RETRY_POLICY (전역 기본값)

    Args:
        name:         ACTIVITY_TIMEOUTS에 정의된 Activity 이름
        retry_policy: RetryPolicy 런타임 오버라이드 — None이면 Activity별 기본값 사용

    Returns:
        start_to_close_timeout과 retry_policy를 담은 딕셔너리

    Raises:
        KeyError: ACTIVITY_TIMEOUTS에 미등록 Activity 이름인 경우
    """
    if name not in ACTIVITY_TIMEOUTS:
        raise KeyError(
            f"Activity {name!r}가 ACTIVITY_TIMEOUTS에 정의되어 있지 않음 "
            f"workflows/activity_options.py를 확인할 것"
        )

    resolved_policy = (
        retry_policy
        or _ACTIVITY_RETRY_OVERRIDES.get(name)
        or DEFAULT_RETRY_POLICY
    )

    return {
        "start_to_close_timeout": ACTIVITY_TIMEOUTS[name],
        "retry_policy": resolved_policy,
    }


def get_all_activity_options() -> dict[str, ActivityOption]:
    """
    전체 Activity 옵션 딕셔너리 반환

    디버깅 및 문서화 용도 — 프로덕션 코드에서 직접 호출 비권장

    예시:
        for name, opts in get_all_activity_options().items():
            print(f"{name}: timeout={opts['start_to_close_timeout']}")
    """
    return {name: get_activity_options(name) for name in ACTIVITY_TIMEOUTS}