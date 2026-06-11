"""
state.py — LangGraph AgentState 정의
전체 에이전트가 공유하는 불변 상태 컨테이너.
각 노드는 이 딕셔너리를 받아서 새 키/값을 추가한 복사본을 반환한다.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any

from typing_extensions import TypedDict


class IncidentEvent(TypedDict):
    """단일 장애 이벤트"""
    pod: str           # "namespace/pod-name"
    node: str          # EKS 노드명
    vpc: str           # "vpc1" | "vpc2"
    reason: str        # "CrashLoopBackOff" | "OOMKilled" | "ImagePullBackOff" | ...
    count: int         # restart count
    timestamp: str     # ISO-8601


class RecoveryPlan(TypedDict):
    """복구 전략 단위"""
    strategy: str      # "restart" | "scale_out" | "rollback" | "investigate"
    target: str        # kubectl/helm 대상 리소스 (e.g. "deployment/backend")
    command: list[str] # 실행할 명령어 리스트
    priority: int      # 1=최우선
    reason: str        # 복구 근거 (RCA 요약)


class AgentState(TypedDict):
    # ── 수집 데이터 ─────────────────────────────────────────────────
    raw_metrics: list[dict[str, Any]]   # Prometheus 메트릭 결과
    raw_logs: list[str]                  # kubectl logs + CW Logs
    _pods_ops: list[dict[str, Any]]     # VPC2 EKS 파드 목록 (내부 전달용)
    _pods_svc: list[dict[str, Any]]     # VPC1 EKS 파드 목록 (내부 전달용)

    # ── 감지 결과 ─────────────────────────────────────────────────
    events: list[IncidentEvent]

    # ── RCA 분석 결과 ─────────────────────────────────────────────
    rca_report: str        # Bedrock 응답 전체 (JSON 문자열)
    rca_root_cause: str    # 핵심 원인 한 줄 요약

    # ── 복구 계획 ─────────────────────────────────────────────────
    plans: list[RecoveryPlan]
    approved_plan: RecoveryPlan | None  # Slack 승인된 계획
    approval_ts: str                    # 승인 타임스탬프

    # ── 실행 결과 ─────────────────────────────────────────────────
    exec_result: str    # 복구 실행 stdout/stderr
    verify_ok: bool     # 5분 후 정상 여부
    rollback_done: bool # 롤백 수행 여부

    # ── LangGraph 메시지 누적 ────────────────────────────────────
    messages: Annotated[list, operator.add]


def initial_state() -> AgentState:
    """빈 초기 상태 반환"""
    return AgentState(
        raw_metrics=[],
        raw_logs=[],
        _pods_ops=[],
        _pods_svc=[],
        events=[],
        rca_report="",
        rca_root_cause="",
        plans=[],
        approved_plan=None,
        approval_ts="",
        exec_result="",
        verify_ok=False,
        rollback_done=False,
        messages=[],
    )
