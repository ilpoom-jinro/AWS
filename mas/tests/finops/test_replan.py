from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

from contracts.models import ReplanIntent


MAS_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_APP = MAS_ROOT / "pods" / "finops" / "orchestrator" / "app"
ORCHESTRATOR_ROOT = MAS_ROOT / "pods" / "finops" / "orchestrator"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runtime = load_module("replan_agent_runtime_test", ORCHESTRATOR_APP / "agent_runtime.py")

sys.path.insert(0, str(ORCHESTRATOR_APP))
sys.path.insert(0, str(ORCHESTRATOR_ROOT))
import chat_runtime  # noqa: E402

for path in (str(ORCHESTRATOR_APP), str(ORCHESTRATOR_ROOT)):
    if path in sys.path:
        sys.path.remove(path)
sys.modules.pop("app", None)
sys.modules.pop("app.chat_tools", None)


class ReplanTests(unittest.TestCase):
    def test_replan_intent_model_validates_valid_payload(self) -> None:
        intent = ReplanIntent(
            intent="replan",
            constraints={"max_pods": 15},
            forbidden_actions=["modify_rds"],
            replan_from="demand_shaping",
            requires_confirmation=True,
            reason="Pod 상한 조건 반영",
        )
        self.assertEqual(intent.constraints["max_pods"], 15)
        self.assertEqual(intent.replan_from, "demand_shaping")

    def test_invalid_replan_from_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ReplanIntent(
                intent="replan",
                constraints={},
                forbidden_actions=[],
                replan_from="unknown_agent",
                requires_confirmation=True,
                reason="invalid",
            )

    def test_agents_before_cost(self) -> None:
        self.assertEqual(
            runtime.agents_before("cost"),
            [
                "business_control",
                "demand_shaping",
                "traffic_forecast",
                "bottleneck_capacity",
                "infra_execution",
            ],
        )

    def test_build_replan_context_injects_constraints(self) -> None:
        intent = ReplanIntent(
            intent="replan",
            constraints={"max_cost_usd": 40},
            forbidden_actions=["modify_rds"],
            replan_from="cost",
            requires_confirmation=True,
            reason="비용 상한 조건 반영",
        )
        previous = {"business_control": {"status": "completed"}}
        context = runtime.build_replan_context(previous, intent)
        self.assertEqual(context["agent_results"], previous)
        self.assertEqual(context["replan_constraints"], {"max_cost_usd": 40})
        self.assertEqual(context["replan_forbidden"], ["modify_rds"])
        self.assertEqual(context["replan_from"], "cost")

    def test_apply_replan_constraints_marks_max_pods_exceeded(self) -> None:
        candidate = runtime.PlanCandidate(
            label="균형",
            push_window_minutes=15,
            required_pods=22,
            estimated_cost_usd=35.0,
            estimated_p95_ms=180.0,
            risk_level="medium",
            budget_exceeded=False,
            policy_violations=[],
        )
        constrained = runtime.apply_replan_constraints(
            [candidate],
            {"max_pods": 15},
        )[0]
        self.assertIn("max_pods_exceeded", constrained.policy_violations)
        self.assertEqual(constrained.risk_level, "high")

    def test_pending_replan_response_shape(self) -> None:
        intent = ReplanIntent(
            intent="replan",
            constraints={"max_pods": 15},
            forbidden_actions=[],
            replan_from="demand_shaping",
            requires_confirmation=True,
            reason="Pod 최대 15개 조건으로 재계획하겠습니다.",
        )
        response = chat_runtime.build_pending_replan_response(
            intent,
            [],
            "Pod 최대 15개까지만 써줘",
        )
        self.assertEqual(response["pending_replan"]["intent"], "replan")
        self.assertIn("run_planner_llm", response["tools_used"])
        self.assertEqual(response["conversation_history"][0]["role"], "user")
        fallback = chat_runtime.planner_fallback()
        self.assertEqual(fallback.intent, "query")
        self.assertEqual(fallback.constraints, {})


if __name__ == "__main__":
    unittest.main()
