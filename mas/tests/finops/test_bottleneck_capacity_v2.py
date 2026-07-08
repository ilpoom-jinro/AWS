from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MAS_ROOT = Path(__file__).resolve().parents[2]
if str(MAS_ROOT) not in sys.path:
    sys.path.insert(0, str(MAS_ROOT))

from contracts.models import AgentResponse, AgentStatus


FINOPS_ROOT = MAS_ROOT / "pods" / "finops"
AGENTS_PATH = str(FINOPS_ROOT / "agents")


def prefer_agents_app_package() -> None:
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            sys.modules.pop(key, None)
    if AGENTS_PATH in sys.path:
        sys.path.remove(AGENTS_PATH)
    sys.path.insert(0, AGENTS_PATH)


def load_agent_logic(directory: str):
    prefer_agents_app_package()
    path = FINOPS_ROOT / directory / "app" / "agent_logic.py"
    spec = importlib.util.spec_from_file_location(f"test_{directory}_v2_logic", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def response_payload(agent_key: str, result: dict) -> dict:
    return AgentResponse(
        status=AgentStatus.COMPLETED,
        agent_key=agent_key,
        agent_name=agent_key,
        result=result,
        message="ok",
        evidence=[],
        data_requests=[],
        confidence=0.9,
        warnings=[],
        reasoning_source="rule",
    ).model_dump(mode="json")


def base_context(
    *,
    rds_cpu: float | None = 4.3,
    rds_source: str = "cloudwatch",
    ready_pods: int = 27,
    peak_rps: int = 1932,
    required_pods: int = 69,
    current_rps: int = 200,
) -> dict:
    rds_metrics = {
        "financial-service-db": {
            "cpu_percent": rds_cpu,
            "connections": 12,
            "source": rds_source,
        },
        "financial-ops-db": {
            "cpu_percent": None,
            "connections": None,
            "source": "cloudwatch_failed",
        },
    }
    return {
        "signals": {
            "db_cpu_percent": 68,
            "cache_hit_ratio_percent": 91,
            "prometheus_rps": current_rps,
        },
        "infra": {},
        "live": {"commands": {}},
        "broker_results": {},
        "agent_results": {
            "cluster_state": response_payload(
                "cluster_state",
                {
                    "rds_metrics": rds_metrics,
                    "rds_cpu_percent": rds_cpu,
                    "rds_connections": 12,
                    "rds_source": rds_source,
                    "scale_target_current_pods": ready_pods,
                },
            ),
            "traffic_forecast": response_payload(
                "traffic_forecast",
                {"peak_rps_after": peak_rps, "required_app_pods": required_pods},
            ),
        },
    }


class BottleneckCapacityV2Tests(unittest.TestCase):
    def test_cloudwatch_value_beats_seed_value(self) -> None:
        result, _ = load_agent_logic("bottleneck-capacity").evaluate(base_context())

        self.assertEqual(result["db_cpu"], 4.3)
        self.assertEqual(result["rds_data_source"], "cloudwatch")

    def test_cloudwatch_failure_falls_back_to_seed_with_warning(self) -> None:
        context = base_context(rds_cpu=None, rds_source="cloudwatch_failed")
        result, _ = load_agent_logic("bottleneck-capacity").evaluate(context)

        self.assertEqual(result["db_cpu"], 68.0)
        self.assertEqual(result["rds_data_source"], "cloudwatch_failed")
        self.assertTrue(any("CloudWatch lookup" in item for item in result["warnings"]))

    def test_pod_readiness_ratio_is_calculated(self) -> None:
        result, _ = load_agent_logic("bottleneck-capacity").evaluate(base_context())

        self.assertEqual(result["pod_readiness_ratio"], 0.39)
        self.assertEqual(result["pod_readiness_percent"], 39.0)
        self.assertTrue(result["pod_readiness_warning"])

    def test_estimated_rds_cpu_at_peak_is_calculated(self) -> None:
        result, _ = load_agent_logic("bottleneck-capacity").evaluate(base_context())

        self.assertEqual(result["estimated_rds_cpu_at_peak"], 41.5)
        self.assertEqual(result["db_risk"], "low")

    def test_db_risk_warning_when_peak_cpu_exceeds_warning_threshold(self) -> None:
        context = base_context(rds_cpu=8.0, current_rps=200, peak_rps=1932)
        result, _ = load_agent_logic("bottleneck-capacity").evaluate(context)

        self.assertEqual(result["estimated_rds_cpu_at_peak"], 77.3)
        self.assertEqual(result["db_risk"], "warning")

    def test_low_pod_readiness_makes_bottleneck_critical(self) -> None:
        result, _ = load_agent_logic("bottleneck-capacity").evaluate(base_context())

        self.assertEqual(result["bottleneck_risk"], "critical")


if __name__ == "__main__":
    unittest.main()
