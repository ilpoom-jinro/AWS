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


def load_agent_logic(directory: str):
    prefer_agents_app_package()
    path = FINOPS_ROOT / directory / "app" / "agent_logic.py"
    spec = importlib.util.spec_from_file_location(f"test_{directory}_reforecast_logic", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def base_context() -> dict:
    return {
        "policy": {"max_general_delay_minutes": 10},
        "signals": {"baseline_peak_rps": 1420, "required_app_pods": 29},
        "traffic": {
            "prometheus_rps": 1420,
            "hpa_desired_replicas": 29,
            "p95_latency_ms": 160,
            "queue_depth": 1000,
        },
        "infra": {"rds_cpu_percent": 75, "redis_cache_hit_ratio_percent": 72},
        "live": {"commands": {}},
        "broker_results": {},
        "agent_results": {
            "demand_shaping": agent_response(
                "demand_shaping",
                {
                    "send_window_minutes": 10,
                    "peak_reduction_percent": 42,
                    "vip_send_mode": "immediate",
                    "general_send_mode": "spread",
                },
            ),
            "traffic_forecast": agent_response(
                "traffic_forecast",
                {
                    "peak_rps_after": 823,
                    "required_app_pods": 29,
                },
            ),
        },
    }


class ReforecastConstraintTests(unittest.TestCase):
    def test_traffic_forecast_handles_updated_constraints_operation(self) -> None:
        traffic = load_agent_logic("traffic-forecast")
        context = base_context()
        context["parameters"] = {
            "operation": "reforecast_with_updated_constraints",
            "peak_rps_after": 823,
            "ready_pods": 14,
            "desired_pods": 29,
            "queue_depth": 7400,
            "p95_latency_ms": 188,
            "pod_memory_percent": 71,
        }

        result, _ = traffic.evaluate(context)

        self.assertTrue(result["reforecast"])
        self.assertEqual(result["reforecast_reason"], "pod_readiness_constraint")
        self.assertIn("pod_scaling_timeline", result)
        self.assertIn("risk_assessment", result)
        self.assertIn("adjusted_capacity_rps", result)

    def test_traffic_forecast_readiness_calculation_matches_expected_values(self) -> None:
        traffic = load_agent_logic("traffic-forecast")
        context = base_context()
        context["parameters"] = {
            "peak_rps_after": 823,
            "ready_pods": 14,
            "desired_pods": 29,
            "queue_depth": 7400,
            "p95_latency_ms": 188,
            "pod_memory_percent": 71,
        }

        result, _ = traffic.evaluate(context)

        self.assertAlmostEqual(result["ready_ratio"], 14 / 29, places=3)
        self.assertAlmostEqual(result["adjusted_capacity_rps"], 823 * (14 / 29), places=2)
        self.assertEqual(result["risk_assessment"]["level"], "high")
        self.assertEqual(result["pod_scaling_timeline"], "T-25m (추가 준비 시간 필요)")
        self.assertEqual(result["required_app_pods"], 29)

    def test_bottleneck_consumes_successful_broker_reforecast_as_tuple(self) -> None:
        bottleneck = load_agent_logic("bottleneck-capacity")
        context = base_context()
        context["broker_results"]["traffic_forecast"] = {
            "_broker_status": "completed",
            "peak_rps_after": 823,
            "required_app_pods": 29,
            "adjusted_capacity_rps": 397.31,
            "pod_scaling_timeline": "T-25m (추가 준비 시간 필요)",
            "risk_assessment": {"level": "high"},
        }

        result, message = bottleneck.evaluate(context)

        self.assertEqual(message, "Reforecast applied with pod readiness constraints")
        self.assertTrue(result["reforecast_applied"])
        self.assertEqual(result["adjusted_capacity_rps"], 397.31)
        self.assertEqual(result["risk_level"], "high")

    def test_bottleneck_falls_back_to_completed_tuple_when_broker_fails(self) -> None:
        bottleneck = load_agent_logic("bottleneck-capacity")
        context = base_context()
        context["broker_results"]["traffic_forecast"] = {
            "_broker_status": "failed",
            "_broker_message": "unsupported operation",
        }

        result, message = bottleneck.evaluate(context)

        self.assertEqual(message, "Using original forecast: broker reforecast failed")
        self.assertFalse(result["reforecast_applied"])
        self.assertIn("broker reforecast failed", result["warnings"][0])
        self.assertEqual(result["validated_rps"], 823)

    def test_static_traffic_forecast_keeps_reforecast_false(self) -> None:
        traffic = load_agent_logic("traffic-forecast")
        result, _ = traffic.evaluate(base_context())

        self.assertFalse(result["reforecast"])


if __name__ == "__main__":
    unittest.main()
