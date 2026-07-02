"""
E2E 스켈레톤 배선 통합 테스트
==============================
FinOps / AIOps / SecOps 세 시나리오의 Workflow 배선이 올바른지
네트워크·Temporal 서버 없이 검증한다.

검증 항목:
  1. Workflow 파일·클래스 존재 여부 (소스 레벨)
  2. HITL signal 이름·시그니처 (소스 파싱 / temporalio 있으면 런타임)
  3. bot.py signal 분기 로직 (parse_action_value, build_approval_blocks)
  4. ActivityName enum이 세 시나리오의 모든 Activity를 포함하는지
  5. get_activity_options()가 올바른 구조를 반환하는지
  6. AIOpsWorkflow의 HITL_TASK_QUEUE가 bot.py 기본값과 일치하는지
  7. contracts 모델의 시나리오-플랜 제약

실행:
    python -m unittest mas.tests.integration.test_skeleton_wiring
    (temporalio 설치 환경에서 전체 런타임 검증 포함)
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path

MAS_ROOT = Path(__file__).resolve().parents[2]
if str(MAS_ROOT) not in sys.path:
    sys.path.insert(0, str(MAS_ROOT))

# temporalio 설치 여부 확인 — 미설치 환경에서 런타임 임포트 테스트를 skip
TEMPORALIO_AVAILABLE = importlib.util.find_spec("temporalio") is not None

AIOPS_WORKFLOW_PATH = MAS_ROOT / "pods" / "aiops" / "orchestrator" / "app" / "workflow.py"
SECOPS_WORKFLOW_PATH = MAS_ROOT / "pods" / "secops" / "orchestrator" / "app" / "workflow.py"
FINOPS_WORKFLOW_PATH = MAS_ROOT / "pods" / "finops" / "orchestrator" / "app" / "workflows.py"
BOT_PATH = MAS_ROOT / "slack-hitl" / "bot.py"
ACTIVITY_OPTIONS_PATH = MAS_ROOT / "workflows" / "activity_options.py"


def _extract_string_constants(source: str, varname: str) -> list[str]:
    """소스 코드에서 특정 변수에 할당된 문자열 상수 목록을 추출한다."""
    tree = ast.parse(source)
    results: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == varname:
                    if isinstance(node.value, ast.Constant):
                        results.append(node.value.s)
    return results


def _find_class_methods(source: str, classname: str) -> list[str]:
    """소스 코드에서 특정 클래스의 메서드 이름 목록을 반환한다 (async def 포함)."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == classname:
            return [
                n.name for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    return []


# ---
# 1. Workflow 파일·클래스 존재 (소스 레벨, temporalio 불필요)
# ---

class TestWorkflowFilesExist(unittest.TestCase):

    def test_aiops_workflow_file_exists(self) -> None:
        self.assertTrue(AIOPS_WORKFLOW_PATH.exists(), f"파일 없음: {AIOPS_WORKFLOW_PATH}")

    def test_aiops_workflow_class_defined(self) -> None:
        source = AIOPS_WORKFLOW_PATH.read_text(encoding="utf-8")
        methods = _find_class_methods(source, "AIOpsRemediationWorkflow")
        self.assertTrue(len(methods) > 0, "AIOpsRemediationWorkflow 클래스 없음")

    def test_secops_workflow_class_defined(self) -> None:
        source = SECOPS_WORKFLOW_PATH.read_text(encoding="utf-8")
        methods = _find_class_methods(source, "SecOpsWorkflow")
        self.assertTrue(len(methods) > 0, "SecOpsWorkflow 클래스 없음")

    def test_finops_workflow_class_defined(self) -> None:
        source = FINOPS_WORKFLOW_PATH.read_text(encoding="utf-8")
        methods = _find_class_methods(source, "FinOpsEventWorkflow")
        self.assertTrue(len(methods) > 0, "FinOpsEventWorkflow 클래스 없음")


# ---
# 2. HITL Signal 이름·시그니처 (소스 레벨)
# ---

class TestHITLSignalsSource(unittest.TestCase):

    def test_aiops_has_approval_result_method(self) -> None:
        source = AIOPS_WORKFLOW_PATH.read_text(encoding="utf-8")
        methods = _find_class_methods(source, "AIOpsRemediationWorkflow")
        self.assertIn("approval_result", methods,
                      "AIOpsRemediationWorkflow에 approval_result 메서드 없음")

    def test_aiops_approval_result_signal_name_annotation(self) -> None:
        """@workflow.signal(name="approval_result") 데코레이터가 소스에 있어야 한다."""
        source = AIOPS_WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn('name="approval_result"', source,
                      "approval_result signal name 어노테이션 없음")

    def test_secops_has_submit_approval_method(self) -> None:
        source = SECOPS_WORKFLOW_PATH.read_text(encoding="utf-8")
        methods = _find_class_methods(source, "SecOpsWorkflow")
        self.assertIn("submit_approval", methods,
                      "SecOpsWorkflow에 submit_approval 메서드 없음")

    def test_hitl_task_queue_default_consistent(self) -> None:
        """AIOps, SecOps, bot.py의 HITL_TASK_QUEUE 기본값이 같아야 한다."""
        def extract_hitl_default(path: Path) -> str | None:
            source = path.read_text(encoding="utf-8")
            for line in source.splitlines():
                if "HITL_TASK_QUEUE" in line and "getenv" in line and "hitl" in line.lower():
                    # os.getenv("HITL_TASK_QUEUE", "hitl-approval-queue") 패턴
                    start = line.rfind('"', 0, line.rfind('"'))
                    end = line.rfind('"')
                    if start != end and start >= 0:
                        return line[start + 1:end]
            return None

        aiops_default = extract_hitl_default(AIOPS_WORKFLOW_PATH)
        secops_default = extract_hitl_default(SECOPS_WORKFLOW_PATH)
        bot_default = extract_hitl_default(BOT_PATH)

        self.assertIsNotNone(aiops_default, "AIOps workflow에서 HITL_TASK_QUEUE 기본값 파싱 실패")
        self.assertIsNotNone(secops_default, "SecOps workflow에서 HITL_TASK_QUEUE 기본값 파싱 실패")
        self.assertEqual(aiops_default, secops_default, "AIOps-SecOps HITL_TASK_QUEUE 기본값 불일치")
        if bot_default:
            self.assertEqual(aiops_default, bot_default, "AIOps-bot.py HITL_TASK_QUEUE 기본값 불일치")

    @unittest.skipUnless(TEMPORALIO_AVAILABLE, "temporalio 미설치 — 컨테이너 환경에서 실행")
    def test_aiops_approval_result_accepts_approval_result_model(self) -> None:
        """런타임: approval_result signal의 파라미터 타입이 ApprovalResult이어야 한다."""
        from pods.aiops.orchestrator.app.workflow import AIOpsRemediationWorkflow
        from contracts.models import ApprovalResult

        sig = inspect.signature(AIOpsRemediationWorkflow.approval_result)
        params = list(sig.parameters.values())
        result_param = params[1]  # params[0] = self
        self.assertIs(result_param.annotation, ApprovalResult)

    @unittest.skipUnless(TEMPORALIO_AVAILABLE, "temporalio 미설치 — 컨테이너 환경에서 실행")
    def test_secops_submit_approval_bool_first_param(self) -> None:
        from pods.secops.orchestrator.app.workflow import SecOpsWorkflow
        sig = inspect.signature(SecOpsWorkflow.submit_approval)
        params = list(sig.parameters.values())
        self.assertIs(params[1].annotation, bool)


# ---
# 3. bot.py signal 분기 로직 (소스 레벨 + 런타임)
# ---

class TestBotSignalRouting(unittest.TestCase):

    def _try_load_bot(self):
        """bot.py를 런타임 로드 시도. slack_bolt 없으면 None 반환."""
        try:
            spec = importlib.util.spec_from_file_location("bot_module", BOT_PATH)
            mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return mod
        except Exception:
            return None

    def test_bot_scenario_field_in_button_value(self) -> None:
        """소스 레벨: build_approval_blocks가 scenario를 버튼 value에 포함해야 한다."""
        source = BOT_PATH.read_text(encoding="utf-8")
        self.assertIn('"scenario"', source,
                      "bot.py build_approval_blocks에서 scenario 필드를 value에 포함하지 않음")
        self.assertIn("request.scenario", source,
                      "bot.py에서 request.scenario를 value JSON에 넣지 않음")

    def test_bot_routes_aiops_to_approval_result(self) -> None:
        """소스 레벨: bot.py가 'aiops' → 'approval_result' signal을 분기해야 한다."""
        source = BOT_PATH.read_text(encoding="utf-8")
        self.assertIn("approval_result", source,
                      "bot.py에 approval_result signal 분기 없음")
        self.assertIn('scenario == "aiops"', source,
                      "bot.py에 aiops 시나리오 분기 없음")

    def test_bot_routes_secops_to_submit_approval(self) -> None:
        source = BOT_PATH.read_text(encoding="utf-8")
        self.assertIn("submit_approval", source,
                      "bot.py에 submit_approval signal 없음")

    def test_parse_action_value_runtime(self) -> None:
        mod = self._try_load_bot()
        if mod is None:
            self.skipTest("slack_bolt 미설치 — 런타임 테스트 건너뜀")
        wf_id, scenario = mod.parse_action_value(
            json.dumps({"wf": "wf-123", "scenario": "aiops"})
        )
        self.assertEqual(wf_id, "wf-123")
        self.assertEqual(scenario, "aiops")

    def test_parse_action_value_defaults_to_secops(self) -> None:
        mod = self._try_load_bot()
        if mod is None:
            self.skipTest("slack_bolt 미설치 — 런타임 테스트 건너뜀")
        _, scenario = mod.parse_action_value(json.dumps({"wf": "wf-999"}))
        self.assertEqual(scenario, "secops")


# ---
# 4 & 5. ActivityName enum 완전성 + get_activity_options 구조
# ---

class TestActivityNameSource(unittest.TestCase):
    """소스 파일을 파싱해 temporalio 없이 ActivityName 멤버를 검증한다."""

    def _load_activity_names(self) -> set[str]:
        source = ACTIVITY_OPTIONS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "ActivityName":
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                names.add(target.id)
        return names

    def test_finops_activities(self) -> None:
        names = self._load_activity_names()
        for required in {"COLLECT_METRICS", "ANALYZE_ANOMALY", "GENERATE_IAC", "APPLY_TERRAFORM"}:
            self.assertIn(required, names, f"ActivityName.{required} 없음")

    def test_aiops_activities(self) -> None:
        names = self._load_activity_names()
        for required in {"DETECT_INCIDENT", "ANALYZE_ROOT_CAUSE",
                         "EXECUTE_REMEDIATION", "VERIFY_RECOVERY", "EXECUTE_ROLLBACK"}:
            self.assertIn(required, names, f"ActivityName.{required} 없음")

    def test_secops_activities(self) -> None:
        names = self._load_activity_names()
        for required in {"DETECT_THREAT", "MAP_REGULATION",
                         "APPLY_ISOLATION", "GENERATE_COMPLIANCE_REPORT"}:
            self.assertIn(required, names, f"ActivityName.{required} 없음")

    def test_common_activities(self) -> None:
        names = self._load_activity_names()
        for required in {"SEND_APPROVAL_REQUEST", "SEND_REMINDER", "RECORD_AUDIT_LOG"}:
            self.assertIn(required, names, f"ActivityName.{required} 없음")

    @unittest.skipUnless(TEMPORALIO_AVAILABLE, "temporalio 미설치 — 컨테이너 환경에서 실행")
    def test_get_activity_options_all_names(self) -> None:
        from workflows.activity_options import ActivityName, get_activity_options
        for name in ActivityName:
            with self.subTest(activity=name):
                opts = get_activity_options(name)
                self.assertIn("start_to_close_timeout", opts)
                self.assertIn("retry_policy", opts)
                self.assertIsInstance(opts["start_to_close_timeout"], timedelta)

    @unittest.skipUnless(TEMPORALIO_AVAILABLE, "temporalio 미설치 — 컨테이너 환경에서 실행")
    def test_state_changing_have_heartbeat(self) -> None:
        from workflows.activity_options import ActivityName, get_activity_options
        for name in (ActivityName.APPLY_TERRAFORM, ActivityName.APPLY_ISOLATION,
                     ActivityName.EXECUTE_REMEDIATION, ActivityName.EXECUTE_ROLLBACK):
            with self.subTest(activity=name):
                self.assertIn("heartbeat_timeout", get_activity_options(name))


# ---
# 6. contracts 모델 시나리오-플랜 제약 (pydantic만 필요)
# ---

class TestContractsPlanConstraints(unittest.TestCase):

    def test_aiops_rejects_wrong_plan(self) -> None:
        from pydantic import ValidationError
        from contracts.models import AnomalyReport, TerraformPlan
        with self.assertRaises(ValidationError):
            AnomalyReport(
                workflow_id="wf-test", scenario="aiops",
                anomaly_type="crashloop_backoff", severity="high",
                affected_resource="pod/test", summary="테스트",
                detail="테스트", confidence=0.9,
                terraform_plan=TerraformPlan(
                    workflow_id="wf-test", hcl_content="resource {}",
                    target_resource="aws_instance.test",
                    estimated_cost_delta_usd=-10.0,
                ),
            )

    def test_secops_rejects_wrong_plan(self) -> None:
        from pydantic import ValidationError
        from contracts.models import ApprovalRequest, RemediationPlan
        with self.assertRaises(ValidationError):
            ApprovalRequest(
                workflow_id="wf-test", scenario="secops",
                severity="high", summary="테스트", detail="테스트",
                remediation_plan=RemediationPlan(
                    workflow_id="wf-test", root_cause="테스트", confidence=0.9,
                    strategy="restart",
                    strategy_detail="[RESTART] pod=test namespace=default | 테스트",
                ),
            )

    def test_remediation_plan_new_fields_safe_defaults(self) -> None:
        from contracts.models import RemediationPlan
        plan = RemediationPlan(
            workflow_id="wf-test", root_cause="테스트", confidence=0.8,
            strategy="restart",
            strategy_detail="[RESTART] pod=test-pod namespace=default | 테스트",
        )
        self.assertEqual(plan.pod_name, "")
        self.assertEqual(plan.previous_hpa_max_replicas, 0)

    def test_remediation_plan_accepts_pod_name(self) -> None:
        from contracts.models import RemediationPlan
        plan = RemediationPlan(
            workflow_id="wf-test", root_cause="테스트", confidence=0.8,
            strategy="scale_out",
            strategy_detail="[SCALE_OUT via HPA] action=patch_hpa target_hpa=my-hpa namespace=prod maxReplicas+=2 | 트래픽 급증",
            pod_name="payment-worker-7d9f",
            previous_hpa_max_replicas=5,
        )
        self.assertEqual(plan.pod_name, "payment-worker-7d9f")
        self.assertEqual(plan.previous_hpa_max_replicas, 5)


if __name__ == "__main__":
    unittest.main()
