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

from contracts.models import ReplanIntent


FINOPS_ROOT = MAS_ROOT / "pods" / "finops"
AGENTS_ROOT = FINOPS_ROOT / "agents"
AGENTS_APP = AGENTS_ROOT / "app"
AGENTS_PATH = str(AGENTS_ROOT)
ORCHESTRATOR_APP = FINOPS_ROOT / "orchestrator" / "app"
ORCHESTRATOR_PATH = str(FINOPS_ROOT / "orchestrator")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def load_dispatch_with_fake_logic(agent_key: str, evaluate):
    prefer_agents_app_package()
    for key in ["app.agent_dispatch", "app.agent_logic"]:
        sys.modules.pop(key, None)
    fake_logic = types.ModuleType("app.agent_logic")
    fake_logic.AGENT_KEY = agent_key
    fake_logic.AGENT_NAME = f"{agent_key} agent"
    fake_logic.LLM_PROMPT = "should not be used"
    fake_logic.evaluate = evaluate
    fake_logic.apply_llm = lambda result, assessment: {"mutated": True, **result}
    sys.modules["app.agent_logic"] = fake_logic
    try:
        module = load_module(
            f"llm_restructure_{agent_key}_dispatch_test",
            AGENTS_APP / "agent_dispatch.py",
        )
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)
        sys.modules.pop("app.agent_logic", None)
    return module


def load_chat_runtime():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            sys.modules.pop(key, None)
    for path in [str(ORCHESTRATOR_APP), ORCHESTRATOR_PATH]:
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    try:
        return load_module(
            "llm_restructure_chat_runtime_test",
            ORCHESTRATOR_APP / "chat_runtime.py",
        )
    finally:
        for path in [str(ORCHESTRATOR_APP), ORCHESTRATOR_PATH]:
            if path in sys.path:
                sys.path.remove(path)
        sys.modules.pop("app", None)
        sys.modules.pop("app.chat_tools", None)


class LlmRestructureTests(unittest.TestCase):
    def test_general_agent_dispatch_does_not_call_rule_correction_llm(self) -> None:
        dispatch = load_dispatch_with_fake_logic(
            "business_control",
            lambda context: ({"event_id": "fomc-briefing"}, "ok"),
        )
        with patch("app.agent_support.call_llm", side_effect=AssertionError("call_llm called")):
            response = asyncio.run(dispatch.run_agent_async("business_control", {}))

        self.assertEqual(response["status"], "completed")
        self.assertNotIn("llm_assessment", response["result"])
        self.assertNotIn("mutated", response["result"])

    def test_general_agent_reasoning_source_is_rule(self) -> None:
        dispatch = load_dispatch_with_fake_logic(
            "business_control",
            lambda context: ({"event_id": "fomc-briefing"}, "ok"),
        )

        response = asyncio.run(dispatch.run_agent_async("business_control", {}))

        self.assertEqual(response["reasoning_source"], "rule")

    def test_run_planner_llm_accepts_partial_replan_intent(self) -> None:
        chat_runtime = load_chat_runtime()

        async def fake_planner(*args, **kwargs):
            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": (
                                    '{"intent":"partial_replan",'
                                    '"constraints":{"push_window_minutes":20},'
                                    '"forbidden_actions":[],'
                                    '"replan_from":"traffic_forecast",'
                                    '"target_agent":"traffic_forecast",'
                                    '"requires_confirmation":true,'
                                    '"reason":"Traffic Forecast만 새 분산 조건으로 재계산"}'
                                )
                            }
                        ]
                    }
                }
            }

        fake_bedrock = types.ModuleType("shared.bedrock")
        fake_bedrock.ClaudeModel = types.SimpleNamespace(HAIKU=types.SimpleNamespace(value="haiku"))
        fake_bedrock.get_bedrock_client = lambda: object()
        with patch.dict("sys.modules", {"shared.bedrock": fake_bedrock}):
            with patch.object(chat_runtime, "_planner_converse_with_timeout", new=fake_planner):
                intent = asyncio.run(
                    chat_runtime.run_planner_llm(
                        conn=object(),
                        workflow_id="finops-test",
                        message="Traffic Forecast만 20분으로 다시 해줘",
                        current_plan={},
                    )
                )

        self.assertEqual(intent.intent, "partial_replan")
        self.assertEqual(intent.target_agent, "traffic_forecast")
        self.assertEqual(intent.constraints["push_window_minutes"], 20)

    def test_replan_intent_has_target_agent_field(self) -> None:
        intent = ReplanIntent(
            intent="partial_replan",
            constraints={"push_window_minutes": 20},
            forbidden_actions=[],
            replan_from="traffic_forecast",
            target_agent="traffic_forecast",
            requires_confirmation=True,
            reason="partial run",
        )

        self.assertEqual(intent.target_agent, "traffic_forecast")

    def test_run_explain_llm_uses_report_tools(self) -> None:
        chat_runtime = load_chat_runtime()

        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def converse(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "output": {
                            "message": {
                                "content": [
                                    {
                                        "toolUse": {
                                            "toolUseId": "tool-1",
                                            "name": "get_quality_gate_result",
                                            "input": {},
                                        }
                                    }
                                ]
                            }
                        }
                    }
                return {
                    "output": {
                        "message": {
                            "content": [
                                {"text": "Quality Gate 이슈 때문에 requires_review 상태입니다."}
                            ]
                        }
                    }
                }

        fake_client = FakeClient()
        fake_bedrock = types.ModuleType("shared.bedrock")
        fake_bedrock.ClaudeModel = types.SimpleNamespace(HAIKU=types.SimpleNamespace(value="haiku"))
        fake_bedrock.get_bedrock_client = lambda: fake_client
        with patch.dict("sys.modules", {"shared.bedrock": fake_bedrock}):
            with patch.object(
                chat_runtime,
                "_invoke_tool",
                return_value={"passed": False, "issues": ["has_blocked_agents"]},
            ) as invoke_tool:
                response = asyncio.run(
                    chat_runtime.run_explain_llm(
                        conn=object(),
                        workflow_id="finops-test",
                        message="지금 왜 이상한거야?",
                        conversation_history=[],
                    )
                )

        invoke_tool.assert_called_once()
        self.assertEqual(response["tools_used"], ["get_quality_gate_result"])
        self.assertIn("Quality Gate", response["answer"])

    def test_static_agent_sequence_still_returns_rule_results(self) -> None:
        dispatch = load_dispatch_with_fake_logic(
            "business_control",
            lambda context: ({"event_id": "fomc-briefing", "grade": "S"}, "ok"),
        )

        response = asyncio.run(dispatch.run_agent_async("business_control", {}))

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["result"]["grade"], "S")
        self.assertEqual(response["reasoning_source"], "rule")


if __name__ == "__main__":
    unittest.main()
