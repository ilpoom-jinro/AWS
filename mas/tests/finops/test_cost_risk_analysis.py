from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

MAS_ROOT = Path(__file__).resolve().parents[2]
if str(MAS_ROOT) not in sys.path:
    sys.path.insert(0, str(MAS_ROOT))


FINOPS_ROOT = MAS_ROOT / "pods" / "finops"
AGENTS_ROOT = FINOPS_ROOT / "agents"
AGENTS_APP = AGENTS_ROOT / "app"
AGENTS_PATH = str(AGENTS_ROOT)


def prefer_agents_app_package() -> None:
    for existing in list(sys.path):
        normalized = existing.replace("\\", "/")
        if normalized.endswith("/mas/pods/finops/agents") or normalized.endswith(
            "/mas/pods/finops/orchestrator"
        ):
            sys.path.remove(existing)
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            sys.modules.pop(key, None)
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
        return load_module("cost_risk_support_test", AGENTS_APP / "agent_support.py")
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


def load_dispatch_with_fake_cost_logic(evaluate=None):
    prefer_agents_app_package()
    fake_logic = types.ModuleType("app.agent_logic")
    fake_logic.AGENT_KEY = "cost"
    fake_logic.AGENT_NAME = "Cost Agent"
    fake_logic.LLM_PROMPT = None
    fake_logic.evaluate = evaluate or (
        lambda context: (
            {
                "estimated_cost_usd": 50.3,
                "budget_usd": 95.0,
                "budget_exceeded": False,
                "warnings": ["rule warning"],
            },
            "cost rule completed",
        )
    )
    fake_logic.apply_llm = lambda result, assessment: result
    sys.modules["app.agent_logic"] = fake_logic
    try:
        return load_module("cost_risk_dispatch_test", AGENTS_APP / "agent_dispatch.py")
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)
        sys.modules.pop("app.agent_logic", None)


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


class CostRiskAnalysisTests(unittest.TestCase):
    def test_cost_risk_judge_returns_dict_not_data_request(self) -> None:
        support = load_agent_support()
        text = (
            '{"warnings":["cost $50.3 is 53% of $95 budget"],'
            '"cost_risk_level":"low",'
            '"cost_risk_summary":"within budget",'
            '"cost_recommendation":"within_budget"}'
        )

        with patch.dict("sys.modules", {"shared.bedrock": fake_bedrock_module(text)}):
            result = asyncio.run(
                support.llm_judge_cost_risk(
                    "cost",
                    {},
                    {"estimated_cost_usd": 50.3, "budget_usd": 95.0},
                )
            )

        self.assertIsInstance(result, dict)
        self.assertEqual(result["cost_risk_level"], "low")
        self.assertEqual(result["cost_recommendation"], "within_budget")
        self.assertIn("53%", result["warnings"][0])

    def test_cost_risk_warnings_are_merged_into_rule_warnings(self) -> None:
        dispatch = load_dispatch_with_fake_cost_logic()
        risk_judge = AsyncMock(
            return_value={
                "warnings": ["cost risk warning"],
                "cost_risk_level": "medium",
                "cost_risk_summary": "approaching budget",
                "cost_recommendation": "approaching_limit",
            }
        )

        with patch.object(dispatch, "llm_judge_cost_risk", new=risk_judge):
            response = asyncio.run(dispatch.run_agent_async("cost", {}))

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["reasoning_source"], "rule+llm")
        self.assertIn("rule warning", response["result"]["warnings"])
        self.assertIn("cost risk warning", response["result"]["warnings"])
        self.assertIn("cost risk warning", response["warnings"])

    def test_cost_dispatch_uses_cost_risk_judge_not_data_request_judge(self) -> None:
        dispatch = load_dispatch_with_fake_cost_logic()
        risk_judge = AsyncMock(
            return_value={
                "warnings": ["cost risk warning"],
                "cost_risk_level": "high",
                "cost_risk_summary": "budget exceeded",
                "cost_recommendation": "exceeded",
            }
        )
        data_request_judge = AsyncMock(return_value=None)

        with patch.object(dispatch, "llm_judge_cost_risk", new=risk_judge), patch.object(
            dispatch,
            "llm_judge_data_request",
            new=data_request_judge,
        ):
            response = asyncio.run(dispatch.run_agent_async("cost", {}))

        self.assertEqual(response["status"], "completed")
        risk_judge.assert_awaited_once()
        data_request_judge.assert_not_called()

    def test_cost_risk_judge_failure_falls_back_to_rule_completed(self) -> None:
        dispatch = load_dispatch_with_fake_cost_logic()
        data_request_judge = AsyncMock(return_value=None)

        with patch.object(
            dispatch,
            "llm_judge_cost_risk",
            new=AsyncMock(return_value=None),
        ), patch.object(dispatch, "llm_judge_data_request", new=data_request_judge):
            response = asyncio.run(dispatch.run_agent_async("cost", {}))

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["reasoning_source"], "rule")
        self.assertNotIn("cost_risk_level", response["result"])
        data_request_judge.assert_not_called()

    def test_cost_result_includes_risk_fields(self) -> None:
        dispatch = load_dispatch_with_fake_cost_logic()
        risk_judge = AsyncMock(
            return_value={
                "warnings": ["cost close to budget"],
                "cost_risk_level": "medium",
                "cost_risk_summary": "cost is approaching limit",
                "cost_recommendation": "approaching_limit",
            }
        )

        with patch.object(dispatch, "llm_judge_cost_risk", new=risk_judge):
            response = asyncio.run(dispatch.run_agent_async("cost", {}))

        self.assertEqual(response["result"]["cost_risk_level"], "medium")
        self.assertEqual(
            response["result"]["cost_risk_summary"],
            "cost is approaching limit",
        )
        self.assertEqual(response["result"]["cost_recommendation"], "approaching_limit")


if __name__ == "__main__":
    unittest.main()
