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

from contracts.models import DataRequest


FINOPS_ROOT = MAS_ROOT / "pods" / "finops"
AGENTS_ROOT = FINOPS_ROOT / "agents"
ORCHESTRATOR_ROOT = FINOPS_ROOT / "orchestrator"
AGENTS_APP = AGENTS_ROOT / "app"
ORCHESTRATOR_APP = ORCHESTRATOR_ROOT / "app"
AGENTS_PATH = str(AGENTS_ROOT)
ORCHESTRATOR_PATH = str(ORCHESTRATOR_ROOT)


def prefer_app_package(path: str) -> None:
    for existing in list(sys.path):
        normalized = existing.replace("\\", "/")
        if normalized.endswith("/mas/pods/finops/agents") or normalized.endswith(
            "/mas/pods/finops/orchestrator"
        ):
            sys.path.remove(existing)
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            sys.modules.pop(key, None)
    sys.path.insert(0, path)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_dispatch_with_fake_logic(
    *,
    agent_key: str = "traffic_forecast",
    agent_name: str = "Traffic Forecast Agent",
    evaluate=None,
):
    prefer_app_package(AGENTS_PATH)
    fake_logic = types.ModuleType("app.agent_logic")
    fake_logic.AGENT_KEY = agent_key
    fake_logic.AGENT_NAME = agent_name
    fake_logic.LLM_PROMPT = None
    fake_logic.evaluate = evaluate or (lambda context: ({"ok": True}, "ok"))
    fake_logic.apply_llm = lambda result, assessment: result
    sys.modules["app.agent_logic"] = fake_logic
    try:
        return load_module("broker_request_dispatch_test", AGENTS_APP / "agent_dispatch.py")
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)
        sys.modules.pop("app.agent_logic", None)


def load_agent_support():
    prefer_app_package(AGENTS_PATH)
    try:
        return load_module("broker_request_support_test", AGENTS_APP / "agent_support.py")
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


def load_workflows():
    prefer_app_package(ORCHESTRATOR_PATH)
    fake_temporalio = types.ModuleType("temporalio")
    fake_workflow = types.SimpleNamespace(
        defn=lambda cls: cls,
        run=lambda fn: fn,
        unsafe=types.SimpleNamespace(
            imports_passed_through=lambda: _NullContextManager(),
        ),
    )
    fake_temporalio.workflow = fake_workflow
    try:
        with patch.dict(
            "sys.modules",
            {
                "temporalio": fake_temporalio,
                "temporalio.workflow": fake_workflow,
            },
        ):
            return load_module("broker_request_workflows_test", ORCHESTRATOR_APP / "workflows.py")
    finally:
        if ORCHESTRATOR_PATH in sys.path:
            sys.path.remove(ORCHESTRATOR_PATH)


class _NullContextManager:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


class BrokerRequestHandlerTests(unittest.TestCase):
    def test_broker_context_calls_handler(self) -> None:
        dispatch = load_dispatch_with_fake_logic(
            evaluate=lambda context: (_ for _ in ()).throw(AssertionError("evaluate should not run"))
        )
        handler = AsyncMock(return_value={"peak_rps_after": 568})
        context = {
            "parameters": {"operation": "validate_forecast", "_broker_request": True},
            "_broker_required_fields": ["peak_rps_after"],
        }
        with patch.object(dispatch, "handle_broker_request", new=handler):
            response = asyncio.run(dispatch.run_agent_async("traffic_forecast", context))

        self.assertEqual(response["status"], "completed")
        handler.assert_awaited_once()

    def test_none_handler_result_returns_not_handled_completed_response(self) -> None:
        dispatch = load_dispatch_with_fake_logic()
        context = {
            "parameters": {"operation": "execute_dry_run_scale", "_broker_request": True},
            "_broker_required_fields": ["dry_run_status"],
        }
        with patch.object(dispatch, "handle_broker_request", new=AsyncMock(return_value=None)):
            response = asyncio.run(dispatch.run_agent_async("traffic_forecast", context))

        self.assertEqual(response["status"], "completed")
        self.assertFalse(response["result"]["_broker_handled"])
        self.assertEqual(response["result"]["_broker_reason"], "not_applicable")
        self.assertIn("not handled", response["warnings"][0])

    def test_dict_handler_result_is_returned_as_completed_response(self) -> None:
        dispatch = load_dispatch_with_fake_logic()
        broker_result = {
            "peak_rps_after": 568,
            "required_app_pods": 21,
        }
        context = {
            "parameters": {"operation": "validate_forecast", "_broker_request": True},
            "_broker_required_fields": ["peak_rps_after", "required_app_pods"],
        }
        with patch.object(
            dispatch,
            "handle_broker_request",
            new=AsyncMock(return_value=broker_result),
        ):
            response = asyncio.run(dispatch.run_agent_async("traffic_forecast", context))

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["result"], broker_result)
        self.assertEqual(response["reasoning_source"], "llm")

    def test_handler_returns_none_when_required_fields_are_missing(self) -> None:
        support = load_agent_support()

        class FakeClient:
            def converse(self, **kwargs):
                return {
                    "output": {
                        "message": {
                            "content": [{"text": '{"peak_rps_after": 568}'}]
                        }
                    }
                }

        fake_bedrock = types.ModuleType("shared.bedrock")
        fake_bedrock.ClaudeModel = types.SimpleNamespace(
            HAIKU=types.SimpleNamespace(value="haiku")
        )
        fake_bedrock.get_bedrock_client = lambda: FakeClient()
        with patch.dict("sys.modules", {"shared.bedrock": fake_bedrock}):
            result = asyncio.run(
                support.handle_broker_request(
                    agent_key="traffic_forecast",
                    agent_name="Traffic Forecast Agent",
                    operation="validate_forecast",
                    parameters={},
                    required_fields=["peak_rps_after", "required_app_pods"],
                    context={},
                )
            )

        self.assertIsNone(result)

    def test_normal_context_uses_existing_dispatch_flow(self) -> None:
        dispatch = load_dispatch_with_fake_logic(
            agent_key="business_control",
            agent_name="Business Control Agent",
            evaluate=lambda context: ({"event_id": "fomc-briefing"}, "ok"),
        )
        handler = AsyncMock(return_value=None)
        with patch.object(dispatch, "handle_broker_request", new=handler):
            response = asyncio.run(dispatch.run_agent_async("business_control", {}))

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["result"]["event_id"], "fomc-briefing")
        handler.assert_not_called()

    def test_workflow_broker_context_shape(self) -> None:
        workflows = load_workflows()
        request = DataRequest(
            target_agent="traffic_forecast",
            operation="validate_forecast",
            parameters={"peak_reduction_percent": 60},
            required_fields=["peak_rps_after", "required_app_pods"],
            reason="test",
        )
        context = {
            "broker_results": {},
            "agent_results": {},
            "broker_cache": {},
        }

        broker_context = workflows.build_broker_agent_context(context, request)

        self.assertTrue(broker_context["parameters"]["_broker_request"])
        self.assertEqual(broker_context["parameters"]["operation"], "validate_forecast")
        self.assertEqual(broker_context["_broker_operation"], "validate_forecast")
        self.assertEqual(
            broker_context["_broker_required_fields"],
            ["peak_rps_after", "required_app_pods"],
        )


if __name__ == "__main__":
    unittest.main()
