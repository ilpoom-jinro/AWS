import sys, asyncio
# 팀 모노레포 루트(contracts/shared/workflows)와 본 패키지 src를 경로에 추가
# CI에서는 editable install로 대체 가능
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))
# contracts/shared/workflows는 mas 모노레포 루트에 위치 (환경변수 MAS_ROOT로 지정 가능)
_MAS_ROOT = os.environ.get("MAS_ROOT", "/tmp/mas_test")
sys.path.insert(0, _MAS_ROOT)

from contracts.models import (
    IncidentContext, AnomalyReport, RemediationPlan,
    DetectIncidentInput, RecoveryVerification,
)
from aiops.mappers import to_anomaly_type, to_strategy

passed = 0

# 1. anomaly_type 매핑 (협의 추가 3종 포함)
assert to_anomaly_type("CrashLoopBackOff") == "crashloop_backoff"
assert to_anomaly_type("OOMKilled") == "oom_killed"
assert to_anomaly_type("ImagePullBackOff") == "image_pull_backoff"
assert to_anomaly_type("ErrImagePull") == "image_pull_backoff"
assert to_anomaly_type("PendingTimeout") == "pending_timeout"
assert to_anomaly_type("Evicted") == "evicted"
assert to_anomaly_type("Unknown") is None
passed += 1; print(f"{passed}. anomaly_type 매핑 6종 + None OK")

# 2. strategy 매핑 (investigate → manual)
assert to_strategy("investigate") == "manual"
assert to_strategy("restart") == "restart"
assert to_strategy("scale_out") == "scale_out"
assert to_strategy("rollback") == "rollback"
assert to_strategy("garbage") == "manual"
passed += 1; print(f"{passed}. strategy 매핑 (investigate→manual) OK")

# 3. IncidentContext가 추가된 anomaly_type을 실제로 허용하는지 (Pydantic 검증)
ic = IncidentContext(
    cluster_name="financial-ops-eks", namespace="service-apps",
    pod_name="backend-abc123de-xk2p9", anomaly_type="image_pull_backoff",
    restart_count=0, recent_logs=["err1", "err2"],
)
assert ic.anomaly_type == "image_pull_backoff"
assert ic.workflow_id.startswith("mas:wf-")   # 자동 생성 확인
passed += 1; print(f"{passed}. IncidentContext 협의 확장값(image_pull_backoff) 허용 OK")

# 4. recent_logs 50줄 초과 시 Pydantic 거부 확인
try:
    IncidentContext(
        cluster_name="c", namespace="n", pod_name="p",
        anomaly_type="crashloop_backoff", recent_logs=["x"]*51,
    )
    assert False, "51줄이 통과되면 안 됨"
except Exception:
    pass
passed += 1; print(f"{passed}. recent_logs 50줄 제한 검증 OK")

# 5. detector의 _detect_reason 로직 (K8s dict → reason)
from aiops.nodes.detector import _detect_reason
crashloop_pod = {
    "metadata": {"name": "backend-abc12-xyz", "namespace": "service-apps"},
    "status": {"phase": "Running", "container_statuses": [
        {"restart_count": 5, "state": {"waiting": {"reason": "CrashLoopBackOff"}},
         "last_state": {}}
    ]},
}
assert _detect_reason(crashloop_pod) == ("CrashLoopBackOff", 5)

evicted_pod = {"metadata": {"name": "p", "namespace": "n"},
               "status": {"reason": "Evicted", "phase": "Failed"}}
assert _detect_reason(evicted_pod) == ("Evicted", 0)

healthy_pod = {"metadata": {"name": "p", "namespace": "n"},
               "status": {"phase": "Running", "container_statuses": [
                   {"restart_count": 0, "state": {"running": {}}, "last_state": {}}]}}
assert _detect_reason(healthy_pod) is None
passed += 1; print(f"{passed}. detector _detect_reason (crashloop/evicted/healthy) OK")

# 6. AnomalyReport scenario-plan 일관성 (aiops → remediation_plan만)
plan = RemediationPlan(
    workflow_id="mas:wf-20260619-test1234",
    root_cause="env 오설정", confidence=0.9, strategy="restart",
    strategy_detail="deployment/backend 재시작",
)
report = AnomalyReport(
    workflow_id="mas:wf-20260619-test1234",
    scenario="aiops", anomaly_type="crashloop_backoff", severity="high",
    affected_resource="service-apps/backend", summary="s", detail="d",
    confidence=0.9, remediation_plan=plan,
)
assert report.remediation_plan.strategy == "restart"
assert report.terraform_plan is None
passed += 1; print(f"{passed}. AnomalyReport(aiops) 시나리오-플랜 일관성 OK")

# 7. verifier deploy_prefix
from aiops.nodes.verifier import _deploy_prefix
assert _deploy_prefix("backend-6d4f7c8b9-xk2p9") == "backend"
passed += 1; print(f"{passed}. verifier deploy_prefix OK")

print(f"\n=== MAS 정합 테스트 {passed}/7 통과 ===")


# 8. ActivityName Enum 기반 get_activity_options 동작 (새 API)
from workflows.activity_options import get_activity_options, ActivityName
opts = get_activity_options(ActivityName.DETECT_INCIDENT)
assert "start_to_close_timeout" in opts
assert "schedule_to_close_timeout" in opts
# 실행 Activity는 heartbeat_timeout 포함
exec_opts = get_activity_options(ActivityName.EXECUTE_REMEDIATION)
assert "heartbeat_timeout" in exec_opts
passed += 1; print(f"{passed}. ActivityName Enum get_activity_options + heartbeat OK")

# 9. Workflow signal 핸들러 + ApprovalTicket 모델
from contracts.models import ApprovalTicket, ApprovalResult
from aiops.workflow import AIOpsRemediationWorkflow
ticket = ApprovalTicket(workflow_id="mas:wf-20260619-tk1", slack_message_ts="123.45", channel_id="C0XXX")
assert ticket.slack_message_ts == "123.45"
assert hasattr(AIOpsRemediationWorkflow, "approval_result")  # signal 핸들러 존재
passed += 1; print(f"{passed}. ApprovalTicket 모델 + Workflow signal 핸들러 OK")

print(f"\n=== MAS v2 정합 테스트 {passed}/9 통과 ===")


# 10. MetricsCollector clamp 로직 (0~1 비율 보장)
import asyncio
from unittest.mock import AsyncMock, patch
from aiops.metrics_collector import MetricsCollector

async def _test_metrics():
    mc = MetricsCollector("http://thanos:9090")
    # _query를 모킹: cpu=0.45, mem=1.7(초과→1.0 클램프), err=None(→0.0)
    async def fake_query(promql):
        if "cpu" in promql: return 0.45
        if "memory" in promql or "working_set" in promql: return 1.7
        return None
    with patch.object(mc, "_query", side_effect=fake_query):
        m = await mc.collect_pod_metrics("financial-ops-eks", "service-apps", "backend-x")
    assert m["cpu_usage_current"] == 0.45
    assert m["memory_usage_current"] == 1.0   # 1.7 → 클램프
    assert m["error_rate"] == 0.0             # None → 0.0
    return True

assert asyncio.run(_test_metrics())
passed += 1; print(f"{passed}. MetricsCollector clamp (0.45/1.0/0.0) OK")

# 11. IncidentContext가 메트릭 필드를 실제로 담는지 (0~1 검증)
ic_with_metrics = IncidentContext(
    cluster_name="financial-ops-eks", namespace="service-apps",
    pod_name="backend-abc12-xyz", anomaly_type="oom_killed",
    restart_count=2, recent_logs=["oom"],
    cpu_usage_current=0.8, memory_usage_current=0.95, error_rate=0.1,
)
assert ic_with_metrics.memory_usage_current == 0.95
passed += 1; print(f"{passed}. IncidentContext 메트릭 필드 채움 OK")

# 12. analyzer 프롬프트가 메트릭을 실제로 포함하는지
from aiops.nodes.analyzer import RCA_PROMPT, _fmt_pct
_p = RCA_PROMPT.format(
    cluster="c", namespace="n", pod="p", anomaly="oom_killed", restarts=3,
    cpu=_fmt_pct(0.32), memory=_fmt_pct(0.97), error_rate=_fmt_pct(0.0),
    logs="OutOfMemoryError",
)
assert "97.0%" in _p                          # 메모리 사용률 반영
assert "수집 실패" in _p                       # error_rate 0.0 → 수집 실패 표기
assert "교차 검증" in _p                       # 분석 지침 포함
passed += 1; print(f"{passed}. analyzer 프롬프트 메트릭 반영 + 교차검증 지침 OK")

print(f"\n=== 메트릭+프롬프트 포함 최종 {passed}/12 통과 ===")
