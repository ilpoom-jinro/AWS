from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MAS_ROOT = Path(__file__).resolve().parents[2]
if str(MAS_ROOT) not in sys.path:
    sys.path.insert(0, str(MAS_ROOT))

from contracts.models import AgentResponse


FINOPS_ROOT = MAS_ROOT / "pods" / "finops"
AGENTS_PATH = str(FINOPS_ROOT / "agents")
AGENTS_APP = FINOPS_ROOT / "agents" / "app"


def prefer_agents_app_package() -> None:
    for path in list(sys.path):
        normalized = path.replace("\\", "/")
        if normalized.endswith("/mas/pods/finops/orchestrator") or normalized.endswith(
            "/mas/pods/finops/ui"
        ):
            sys.path.remove(path)
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            sys.modules.pop(key, None)
    if AGENTS_PATH in sys.path:
        sys.path.remove(AGENTS_PATH)
    sys.path.insert(0, AGENTS_PATH)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_unit_economics_logic():
    prefer_agents_app_package()
    try:
        return load_module(
            "unit_economics_capability_logic_test",
            FINOPS_ROOT / "unit-economics" / "app" / "agent_logic.py",
        )
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


def load_agent_support():
    prefer_agents_app_package()
    try:
        return load_module(
            "unit_economics_capability_support_test",
            AGENTS_APP / "agent_support.py",
        )
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


def agent_response(agent_key: str, result: dict) -> dict:
    return AgentResponse(
        status="completed",
        agent_key=agent_key,
        agent_name=agent_key,
        result=result,
        message="ok",
        evidence=[],
        data_requests=[],
        confidence=0.8,
        warnings=[],
        reasoning_source="rule",
    ).model_dump(mode="json")


def unit_context(
    *,
    estimated_cost_usd: float = 50.3,
    expected_value_usd: float = 4200.0,
    grade: str = "S",
    target_users: int = 350000,
    approval_threshold: float = 95.0,
    ready_pods: int = 29,
    required_pods: int = 29,
) -> dict:
    return {
        "grade": grade,
        "target_users": target_users,
        "event_incremental_budget_usd": approval_threshold,
        "ready_app_pods": ready_pods,
        "required_app_pods": required_pods,
        "signals": {"expected_value_usd": expected_value_usd},
        "agent_results": {
            "cost": agent_response(
                "cost",
                {
                    "total": estimated_cost_usd,
                    "estimated_cost_usd": estimated_cost_usd,
                },
            )
        },
    }


class UnitEconomicsCapabilityTests(unittest.TestCase):
    def test_cost_efficiency_score_is_calculated(self) -> None:
        unit = load_unit_economics_logic()
        result, _message = unit.evaluate(unit_context())

        self.assertEqual(result["cost_efficiency_score"], round(4200 / 50.3, 2))

    def test_roi_validation_is_positive_or_negative(self) -> None:
        unit = load_unit_economics_logic()

        self.assertEqual(unit.validate_roi(83.5), "positive")
        self.assertEqual(unit.validate_roi(0.5), "negative")

    def test_business_impact_assessment(self) -> None:
        unit = load_unit_economics_logic()

        self.assertEqual(
            unit.assess_business_impact("S", 350000),
            "high_value_tier1_event",
        )
        self.assertEqual(
            unit.assess_business_impact("A", 50000),
            "medium_value_event",
        )

    def test_final_approval_recommendation(self) -> None:
        unit = load_unit_economics_logic()

        self.assertEqual(
            unit.recommend_final_approval(50.3, 95, 29, 29),
            "auto_approvable",
        )
        self.assertEqual(
            unit.recommend_final_approval(50.3, 95, 14, 29),
            "requires_human_approval_infra_risk",
        )
        self.assertEqual(
            unit.recommend_final_approval(100.0, 95, 29, 29),
            "requires_human_approval_budget_exceeded",
        )
        self.assertEqual(
            unit.recommend_final_approval(100.0, 95, 14, 29),
            "requires_human_approval_budget_and_infra_risk",
        )

    def test_agent_capabilities_register_new_fields(self) -> None:
        support = load_agent_support()
        fields = support.AGENT_CAPABILITIES["unit_economics"]["fields"]

        for field in [
            "cost_efficiency_score",
            "roi_validation",
            "business_impact_assessment",
            "final_approval_recommendation",
        ]:
            self.assertIn(field, fields)

    def test_llm_judge_filter_allows_new_fields(self) -> None:
        support = load_agent_support()
        required_fields = [
            "cost_efficiency_score",
            "roi_validation",
            "business_impact_assessment",
            "final_approval_recommendation",
        ]

        filtered = support.filter_required_fields_by_capability(
            "unit_economics",
            required_fields,
        )

        self.assertEqual(filtered, required_fields)


if __name__ == "__main__":
    unittest.main()
