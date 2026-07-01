from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

MAS_ROOT = Path(__file__).resolve().parents[2]
if str(MAS_ROOT) not in sys.path:
    sys.path.insert(0, str(MAS_ROOT))

from contracts.models import AgentResponse


FINOPS_ROOT = MAS_ROOT / "pods" / "finops"
AGENTS_PATH = str(FINOPS_ROOT / "agents")


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
        return load_module("capability_agent_support_test", FINOPS_ROOT / "agents" / "app" / "agent_support.py")
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


def load_agent_logic(directory: str):
    prefer_agents_app_package()
    try:
        return load_module(
            f"capability_{directory}_logic_test",
            FINOPS_ROOT / directory / "app" / "agent_logic.py",
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


class CapabilityContractTests(unittest.TestCase):
    def test_traffic_forecast_capability_contains_demand_shaping_reforecast(self) -> None:
        support = load_agent_support()

        self.assertIn("traffic_forecast", support.AGENT_CAPABILITIES)
        self.assertIn(
            "reforecast_with_demand_shaping_update",
            support.AGENT_CAPABILITIES["traffic_forecast"]["operations"],
        )

    def test_resolver_extracts_estimated_p95_from_candidate_forecasts(self) -> None:
        support = load_agent_support()
        agent_result = {
            "candidate_forecasts": [
                {"estimated_p95_ms": 129.75, "peak_rps_after": 568}
            ]
        }

        resolved = support.resolve_fields_from_context(
            "traffic_forecast",
            ["estimated_p95_ms", "peak_rps_after"],
            agent_result,
        )

        self.assertEqual(
            resolved,
            {"estimated_p95_ms": 129.75, "peak_rps_after": 568},
        )

    def test_handle_broker_request_returns_resolved_fields_without_llm(self) -> None:
        support = load_agent_support()
        context = {
            "agent_results": {
                "traffic_forecast": agent_response(
                    "traffic_forecast",
                    {
                        "candidate_forecasts": [
                            {
                                "peak_rps_after": 568,
                                "required_app_pods": 21,
                                "estimated_p95_ms": 129.75,
                            }
                        ]
                    },
                )
            }
        }

        with patch.object(support, "_parse_json") as parse_json:
            result = asyncio.run(
                support.handle_broker_request(
                    agent_key="traffic_forecast",
                    agent_name="Traffic Forecast Agent",
                    operation="reforecast_with_demand_shaping_update",
                    parameters={"send_window_minutes": 15},
                    required_fields=[
                        "peak_rps_after",
                        "required_app_pods",
                        "estimated_p95_ms",
                    ],
                    context=context,
                )
            )

        self.assertEqual(
            result,
            {
                "peak_rps_after": 568,
                "required_app_pods": 21,
                "estimated_p95_ms": 129.75,
            },
        )
        parse_json.assert_not_called()

    def test_handle_broker_request_rejects_unknown_operation(self) -> None:
        support = load_agent_support()

        result = asyncio.run(
            support.handle_broker_request(
                agent_key="traffic_forecast",
                agent_name="Traffic Forecast Agent",
                operation="execute_real_scale",
                parameters={},
                required_fields=["peak_rps_after"],
                context={},
            )
        )

        self.assertIsNone(result)

    def test_all_finops_agents_have_capability_md(self) -> None:
        expected = [
            "traffic-forecast",
            "observer",
            "bottleneck-capacity",
            "infra-execution",
            "cost",
            "unit-economics",
            "policy-guardrail",
            "fallback",
            "postmortem-learning",
            "business-control",
            "demand-shaping",
        ]

        missing = [
            directory
            for directory in expected
            if not (FINOPS_ROOT / directory / "capability.md").exists()
        ]

        self.assertEqual(missing, [])

    def test_observer_completes_when_broker_reforecast_failed(self) -> None:
        observer = load_agent_logic("observer")
        context = {
            "signals": {"scale_down_rps_threshold": 600},
            "broker_results": {
                "traffic_forecast": {
                    "_broker_status": "failed",
                    "_broker_reason": "missing_required_fields",
                }
            },
            "agent_results": {
                "traffic_forecast": agent_response(
                    "traffic_forecast",
                    {"peak_rps_after": 823, "required_app_pods": 29, "p95_latency_ms": 188},
                ),
                "policy_guardrail": agent_response(
                    "policy_guardrail",
                    {"approval_required": True, "allowed": True},
                ),
            },
        }

        response = observer.evaluate(context)

        self.assertIsInstance(response, AgentResponse)
        self.assertEqual(response.status, "completed")
        self.assertTrue(response.result["broker_reforecast_applied"] is False)
        self.assertIn("broker reforecast failed", response.warnings[0])


if __name__ == "__main__":
    unittest.main()
