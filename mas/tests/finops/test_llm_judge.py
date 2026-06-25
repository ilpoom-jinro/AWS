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

from contracts.models import AGENT_ALLOWED_REQUESTS, AgentResponse, AgentStatus, DataRequest


AGENTS_ROOT = MAS_ROOT / "pods" / "finops" / "agents"
AGENTS_APP = AGENTS_ROOT / "app"
AGENTS_PATH = str(AGENTS_ROOT)


def prefer_agents_app_package() -> None:
    for path in list(sys.path):
        normalized = path.replace("\\", "/")
        if normalized.endswith("/mas/pods/finops/orchestrator") or normalized.endswith("/mas/pods/finops/ui"):
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
        return load_module("llm_judge_agent_support_test", AGENTS_APP / "agent_support.py")
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


def load_dispatch_with_fake_logic(evaluate):
    prefer_agents_app_package()
    for key in ["app.agent_dispatch", "app.agent_logic"]:
        sys.modules.pop(key, None)
    fake_logic = types.ModuleType("app.agent_logic")
    fake_logic.AGENT_KEY = "bottleneck_capacity"
    fake_logic.AGENT_NAME = "Bottleneck Capacity Agent"
    fake_logic.LLM_PROMPT = None
    fake_logic.evaluate = evaluate
    fake_logic.apply_llm = lambda result, assessment: result
    sys.modules["app.agent_logic"] = fake_logic
    try:
        module = load_module("llm_judge_dispatch_test", AGENTS_APP / "agent_dispatch.py")
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)
        sys.modules.pop("app.agent_logic", None)
    return module


class LlmJudgeTests(unittest.TestCase):
    def test_none_judge_falls_back_to_completed(self) -> None:
        dispatch = load_dispatch_with_fake_logic(lambda context: ({"db_cpu": 75}, "ok"))
        with patch.object(dispatch, "llm_judge_data_request", new=AsyncMock(return_value=None)):
            response = asyncio.run(dispatch.run_agent_async("bottleneck_capacity", {}))
        self.assertEqual(response["status"], "completed")

    def test_data_request_judge_returns_needs_data(self) -> None:
        request = DataRequest(
            target_agent="traffic_forecast",
            operation="reforecast",
            parameters={"push_window_minutes": 20},
            required_fields=["peak_rps_after"],
            reason="복합 지표 위험, 재예측 권장",
        )
        dispatch = load_dispatch_with_fake_logic(lambda context: ({"db_cpu": 75}, "ok"))
        with patch.object(dispatch, "llm_judge_data_request", new=AsyncMock(return_value=request)):
            response = asyncio.run(dispatch.run_agent_async("bottleneck_capacity", {}))
        self.assertEqual(response["status"], "needs_data")
        self.assertEqual(response["data_requests"][0]["target_agent"], "traffic_forecast")

    def test_disallowed_target_is_ignored(self) -> None:
        support = load_agent_support()

        class FakeClient:
            def converse(self, **kwargs):
                return {
                    "output": {
                        "message": {
                            "content": [
                                {
                                    "text": (
                                        '{"target_agent":"cost","operation":"estimate",'
                                        '"parameters":{},"required_fields":[],"reason":"bad"}'
                                    )
                                }
                            ]
                        }
                    }
                }

        fake_bedrock = types.ModuleType("shared.bedrock")
        fake_bedrock.ClaudeModel = types.SimpleNamespace(HAIKU=types.SimpleNamespace(value="haiku"))
        fake_bedrock.get_bedrock_client = lambda: FakeClient()
        with patch.dict("sys.modules", {"shared.bedrock": fake_bedrock}):
            result = asyncio.run(
                support.llm_judge_data_request(
                    "bottleneck_capacity",
                    {},
                    {},
                    ["traffic_forecast"],
                )
            )
        self.assertIsNone(result)

    def test_llm_exception_returns_none(self) -> None:
        support = load_agent_support()
        with patch.dict("sys.modules", {"shared.bedrock": None}):
            result = asyncio.run(
                support.llm_judge_data_request(
                    "bottleneck_capacity",
                    {},
                    {},
                    ["traffic_forecast"],
                )
            )
        self.assertIsNone(result)

    def test_agent_without_allowed_requests_skips_judge(self) -> None:
        self.assertNotIn("business_control", AGENT_ALLOWED_REQUESTS)

        def evaluate(context):
            return {"event_id": "normal-event"}, "ok"

        dispatch = load_dispatch_with_fake_logic(evaluate)
        dispatch.agent_logic.AGENT_KEY = "business_control"
        dispatch.agent_logic.AGENT_NAME = "Business Control Agent"
        judge = AsyncMock(return_value=None)
        with patch.object(dispatch, "llm_judge_data_request", new=judge):
            response = asyncio.run(dispatch.run_agent_async("business_control", {}))
        self.assertEqual(response["status"], "completed")
        judge.assert_not_called()

    def test_agent_response_needs_data_skips_judge(self) -> None:
        request = DataRequest(
            target_agent="traffic_forecast",
            operation="reforecast",
            parameters={},
            required_fields=["peak_rps_after"],
            reason="hardcoded condition",
        )
        hardcoded = AgentResponse(
            status=AgentStatus.NEEDS_DATA,
            agent_key="bottleneck_capacity",
            agent_name="Bottleneck Capacity Agent",
            result={},
            message="hardcoded condition",
            evidence=[],
            data_requests=[request],
            confidence=0.7,
            warnings=[],
            reasoning_source="rule",
        )
        dispatch = load_dispatch_with_fake_logic(lambda context: hardcoded)
        judge = AsyncMock(return_value=None)
        with patch.object(dispatch, "llm_judge_data_request", new=judge):
            response = asyncio.run(dispatch.run_agent_async("bottleneck_capacity", {}))
        self.assertEqual(response["status"], "needs_data")
        judge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
