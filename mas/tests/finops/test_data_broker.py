from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from contracts.models import AgentResponse, AgentStatus, DataRequest


RUNTIME_PATH = (
    Path(__file__).resolve().parents[2]
    / "pods"
    / "finops"
    / "orchestrator"
    / "app"
    / "agent_runtime.py"
)
FINOPS_ROOT = Path(__file__).resolve().parents[2] / "pods" / "finops"
sys.path.insert(0, str(FINOPS_ROOT / "agents"))
SPEC = importlib.util.spec_from_file_location("finops_agent_runtime_test", RUNTIME_PATH)
runtime = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runtime)


def broker_context() -> dict:
    return {
        "broker_total_calls": 0,
        "broker_agent_calls": {},
    }


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


def load_agent_logic(directory: str):
    path = FINOPS_ROOT / directory / "app" / "agent_logic.py"
    spec = importlib.util.spec_from_file_location(f"test_{directory}_logic", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DataBrokerUnitTests(unittest.TestCase):
    def test_cache_key_is_deterministic(self) -> None:
        first = DataRequest(
            target_agent="traffic_forecast",
            operation="reforecast",
            parameters={"window": 20, "region": "서울"},
            required_fields=["peak_rps_after"],
            reason="test",
        )
        second = DataRequest(
            target_agent="traffic_forecast",
            operation="reforecast",
            parameters={"region": "서울", "window": 20},
            required_fields=["peak_rps_after"],
            reason="test",
        )
        self.assertEqual(runtime.broker_cache_key(first), runtime.broker_cache_key(second))

        context = {"broker_cache": {runtime.broker_cache_key(first): {"value": 568}}}
        self.assertEqual(
            runtime.get_broker_cached_result(context, second),
            {"value": 568},
        )

    def test_cycle_is_rejected(self) -> None:
        failure = runtime.broker_guard_failure(
            broker_context(),
            "traffic_forecast",
            ["bottleneck_capacity", "traffic_forecast"],
        )
        self.assertEqual(failure["_broker_status"], "failed")
        self.assertEqual(failure["_broker_reason"], "cycle_detected")

    def test_max_depth_is_rejected(self) -> None:
        failure = runtime.broker_guard_failure(
            broker_context(),
            "cost",
            ["agent_a", "agent_b", "agent_c"],
        )
        self.assertEqual(failure["_broker_reason"], "max_depth")

    def test_agent_call_limit_is_rejected(self) -> None:
        context = broker_context()
        context["broker_agent_calls"]["cost"] = runtime.BROKER_MAX_AGENT_CALLS
        failure = runtime.broker_guard_failure(context, "cost", ["observer"])
        self.assertEqual(failure["_broker_reason"], "agent_call_limit")

    def test_total_call_limit_is_rejected(self) -> None:
        context = broker_context()
        context["broker_total_calls"] = runtime.BROKER_MAX_TOTAL_CALLS
        failure = runtime.broker_guard_failure(context, "cost", ["observer"])
        self.assertEqual(failure["_broker_status"], "failed")
        self.assertEqual(failure["_broker_reason"], "total_call_limit")

    def test_required_fields_are_extracted(self) -> None:
        response = AgentResponse(
            status="completed",
            agent_key="traffic_forecast",
            agent_name="Traffic Forecast Agent",
            result={
                "peak_rps_after": 568,
                "required_app_pods": 29,
                "ignored": True,
            },
            message="ok",
            evidence=[],
            data_requests=[],
            confidence=0.8,
            warnings=[],
            reasoning_source="rule",
        )
        result = runtime.extract_required_fields(
            response,
            ["peak_rps_after", "required_app_pods"],
        )
        self.assertEqual(
            result,
            {
                "_broker_status": "completed",
                "peak_rps_after": 568,
                "required_app_pods": 29,
            },
        )

    def test_missing_required_field_returns_failure_shape(self) -> None:
        response = AgentResponse(
            status="completed",
            agent_key="traffic_forecast",
            agent_name="Traffic Forecast Agent",
            result={"peak_rps_after": 568},
            message="ok",
            evidence=[],
            data_requests=[],
            confidence=0.8,
            warnings=[],
            reasoning_source="rule",
        )
        result = runtime.extract_required_fields(response, ["required_app_pods"])
        self.assertEqual(result["_broker_status"], "failed")
        self.assertEqual(result["_broker_reason"], "missing_required_fields")
        self.assertIn("_broker_message", result)

    def test_bottleneck_requests_and_consumes_traffic_reforecast(self) -> None:
        traffic = load_agent_logic("traffic-forecast")
        bottleneck = load_agent_logic("bottleneck-capacity")
        context = {
            "policy": {"max_general_delay_minutes": 2},
            "signals": {"baseline_peak_rps": 1420, "required_app_pods": 29},
            "traffic": {"prometheus_rps": 1420, "hpa_desired_replicas": 29},
            "infra": {"rds_cpu_percent": 85, "redis_cache_hit_ratio_percent": 91},
            "live": {"commands": {}},
            "broker_results": {},
            "agent_results": {
                "demand_shaping": agent_response(
                    "demand_shaping",
                    {
                        "send_window_minutes": 2,
                        "peak_reduction_percent": 10,
                        "vip_send_mode": "immediate",
                        "general_send_mode": "spread",
                    },
                ),
                "traffic_forecast": agent_response(
                    "traffic_forecast",
                    {
                        "peak_rps_after": 1278,
                        "required_app_pods": 29,
                    },
                ),
            },
        }

        request_response = bottleneck.evaluate(context)
        self.assertIsInstance(request_response, AgentResponse)
        self.assertEqual(request_response.status, AgentStatus.NEEDS_DATA)
        request = request_response.data_requests[0]

        traffic_context = {**context, "parameters": request.parameters}
        reforecast, _ = traffic.evaluate(traffic_context)
        self.assertTrue(reforecast["reforecast"])
        reforecast_response = AgentResponse(
            status="completed",
            agent_key="traffic_forecast",
            agent_name="Traffic Forecast Agent",
            result=reforecast,
            message="ok",
            evidence=[],
            data_requests=[],
            confidence=0.8,
            warnings=[],
            reasoning_source="rule",
        )
        resolved = runtime.extract_required_fields(
            reforecast_response,
            request.required_fields,
        )
        self.assertEqual(resolved["_broker_status"], "completed")
        self.assertLess(resolved["peak_rps_after"], 1000)

        context["broker_results"]["traffic_forecast"] = resolved
        completed = bottleneck.evaluate(context)
        self.assertIsInstance(completed, AgentResponse)
        self.assertEqual(completed.status, AgentStatus.COMPLETED)
        self.assertEqual(
            completed.result["validated_rps"],
            resolved["peak_rps_after"],
        )

    def test_static_bottleneck_path_is_unchanged(self) -> None:
        bottleneck = load_agent_logic("bottleneck-capacity")
        context = {
            "signals": {},
            "infra": {"rds_cpu_percent": 68, "redis_cache_hit_ratio_percent": 91},
            "live": {"commands": {}},
            "broker_results": {},
            "agent_results": {
                "traffic_forecast": agent_response(
                    "traffic_forecast",
                    {"peak_rps_after": 823, "required_app_pods": 29},
                )
            },
        }
        result = bottleneck.evaluate(context)
        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0]["validated_rps"], 823)


if __name__ == "__main__":
    unittest.main()
