from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

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


def load_agent_support():
    prefer_agents_app_package()
    try:
        return load_module(
            "llm_judge_capability_agent_support_test",
            AGENTS_APP / "agent_support.py",
        )
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


def load_policy_guardrail_logic():
    prefer_agents_app_package()
    try:
        return load_module(
            "llm_judge_capability_policy_guardrail_test",
            FINOPS_ROOT / "policy-guardrail" / "app" / "agent_logic.py",
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


class FakeClient:
    def __init__(self, text: str) -> None:
        self.text = text

    def converse(self, **kwargs):
        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": self.text,
                        }
                    ]
                }
            }
        }


def fake_bedrock_module(text: str):
    fake_bedrock = types.ModuleType("shared.bedrock")
    fake_bedrock.ClaudeModel = types.SimpleNamespace(
        HAIKU=types.SimpleNamespace(value="haiku")
    )
    fake_bedrock.get_bedrock_client = lambda: FakeClient(text)
    return fake_bedrock


def policy_context(broker_data: dict | None = None) -> dict:
    context = {
        "policy": {"approval_required": False},
        "policy_source": {
            "allowed_actions": ["scale_out", "prewarm", "spread_push"],
            "forbidden_actions": [],
            "approval_required_over_usd": 50.0,
            "monthly_budget_limit_usd": 30000.0,
            "policy_version": "test",
        },
        "agent_results": {
            "unit_economics": agent_response(
                "unit_economics",
                {
                    "override": False,
                    "cost_ratio": "1.2%",
                    "estimated_cost_usd": 50.3,
                    "expected_value_usd": 4200.0,
                },
            )
        },
    }
    if broker_data is not None:
        context["broker_results"] = {"unit_economics": broker_data}
    return context


class LlmJudgeCapabilityFilterTests(unittest.TestCase):
    def test_required_fields_are_filtered_by_target_capability(self) -> None:
        support = load_agent_support()

        filtered = support.filter_required_fields_by_capability(
            "unit_economics",
            ["cost_ratio", "cost_efficiency_score", "roi_validation"],
        )

        self.assertEqual(filtered, ["cost_ratio"])

    def test_llm_judge_returns_none_when_filtered_fields_are_empty(self) -> None:
        support = load_agent_support()
        text = (
            '{"target_agent":"unit_economics",'
            '"operation":"validate_cost_efficiency_with_business_impact",'
            '"parameters":{},'
            '"required_fields":["cost_efficiency_score","roi_validation"],'
            '"reason":"unsupported fields"}'
        )

        with patch.dict("sys.modules", {"shared.bedrock": fake_bedrock_module(text)}):
            result = asyncio.run(
                support.llm_judge_data_request(
                    "policy_guardrail",
                    {},
                    {},
                    ["unit_economics"],
                )
            )

        self.assertIsNone(result)

    def test_unknown_target_keeps_required_fields(self) -> None:
        support = load_agent_support()
        text = (
            '{"target_agent":"custom_agent",'
            '"operation":"custom_operation",'
            '"parameters":{},'
            '"required_fields":["custom_field"],'
            '"reason":"custom target"}'
        )

        with patch.dict("sys.modules", {"shared.bedrock": fake_bedrock_module(text)}):
            result = asyncio.run(
                support.llm_judge_data_request(
                    "policy_guardrail",
                    {},
                    {},
                    ["custom_agent"],
                )
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.required_fields, ["custom_field"])

    def test_prompt_summary_includes_capability_fields(self) -> None:
        support = load_agent_support()

        summary = support.build_agent_capability_field_summary(["unit_economics"])

        self.assertIn("unit_economics", summary)
        self.assertIn("cost_ratio", summary)
        self.assertIn("estimated_cost_usd", summary)
        self.assertIn("expected_value_usd", summary)
        self.assertIn("override", summary)

    def test_policy_guardrail_completes_when_broker_failed(self) -> None:
        policy_guardrail = load_policy_guardrail_logic()
        response = policy_guardrail.evaluate(
            policy_context(
                {
                    "_broker_status": "failed",
                    "_broker_reason": "missing_required_fields",
                }
            )
        )

        self.assertIsInstance(response, AgentResponse)
        self.assertEqual(response.status, "completed")
        self.assertTrue(response.result["approval_required"])
        self.assertIn("additional validation unavailable", response.warnings[0])

    def test_policy_guardrail_completes_when_broker_succeeded(self) -> None:
        policy_guardrail = load_policy_guardrail_logic()
        response = policy_guardrail.evaluate(
            policy_context(
                {
                    "_broker_status": "completed",
                    "cost_ratio": "1.2%",
                    "estimated_cost_usd": 50.3,
                }
            )
        )

        self.assertIsInstance(response, AgentResponse)
        self.assertEqual(response.status, "completed")
        self.assertEqual(
            response.result["unit_economics_additional_validation"]["cost_ratio"],
            "1.2%",
        )


if __name__ == "__main__":
    unittest.main()
