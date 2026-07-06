from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


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
    spec = importlib.util.spec_from_file_location(f"test_{directory}_history_logic", path)
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


class HistoryBaselineTests(unittest.TestCase):
    def test_business_control_calculates_baseline_from_event_history(self) -> None:
        logic = load_agent_logic("business-control")
        history = [
            {"event_date": "2025-11-07", "actual_peak_rps": 1380, "actual_shaped_rps": 800, "actual_pods_used": 26, "actual_cost_usd": 47.2, "actual_p95_ms": 181},
            {"event_date": "2025-09-18", "actual_peak_rps": 1450, "actual_shaped_rps": 850, "actual_pods_used": 31, "actual_cost_usd": 53.1, "actual_p95_ms": 195},
            {"event_date": "2025-07-30", "actual_peak_rps": 1290, "actual_shaped_rps": 750, "actual_pods_used": 23, "actual_cost_usd": 42.8, "actual_p95_ms": 172},
            {"event_date": "2025-05-07", "actual_peak_rps": 1350, "actual_shaped_rps": 780, "actual_pods_used": 25, "actual_cost_usd": 45.5, "actual_p95_ms": 178},
            {"event_date": "2025-03-19", "actual_peak_rps": 1260, "actual_shaped_rps": 730, "actual_pods_used": 22, "actual_cost_usd": 41.2, "actual_p95_ms": 168},
        ]
        context = {
            "event": {"event_id": "fomc-briefing", "title": "FOMC", "grade": "S", "target_users": 350000},
            "policy": {"approval_required": True, "max_general_delay_minutes": 10},
            "business": {},
        }

        with patch.object(logic, "_query_event_history", return_value=history):
            result, _ = logic.evaluate(context)

        self.assertEqual(result["baseline_peak_rps"], 1346)
        self.assertEqual(result["historical_avg_shaped_rps"], 782)
        self.assertEqual(result["historical_avg_pods"], 25.4)

    def test_business_control_uses_default_baseline_without_history(self) -> None:
        logic = load_agent_logic("business-control")
        context = {
            "event": {"event_id": "fomc-briefing", "title": "FOMC", "grade": "S", "target_users": 350000},
            "policy": {"approval_required": True, "max_general_delay_minutes": 10},
            "business": {},
        }

        with patch.object(logic, "_query_event_history", return_value=[]):
            result, _ = logic.evaluate(context)

        self.assertEqual(result["baseline_peak_rps"], 1400)
        self.assertEqual(result["historical_event_count"], 0)

    def test_traffic_forecast_prioritizes_business_control_baseline(self) -> None:
        logic = load_agent_logic("traffic-forecast")
        context = {
            "policy": {"max_general_delay_minutes": 10},
            "signals": {"baseline_peak_rps": 9999, "required_app_pods": 29},
            "traffic": {"prometheus_rps": 9999, "p95_latency_ms": 188},
            "agent_results": {
                "business_control": response_payload(
                    "business_control",
                    {"baseline_peak_rps": 1346, "historical_avg_shaped_rps": 782},
                ),
                "demand_shaping": response_payload(
                    "demand_shaping",
                    {"send_window_minutes": 10, "peak_reduction_percent": 42},
                ),
            },
        }

        result, _ = logic.evaluate(context)

        self.assertEqual(result["peak_rps_before"], 1346)
        self.assertEqual(result["peak_rps_after"], 780)

    def test_traffic_forecast_variance_from_history(self) -> None:
        logic = load_agent_logic("traffic-forecast")
        context = {
            "policy": {"max_general_delay_minutes": 10},
            "signals": {"required_app_pods": 29},
            "traffic": {"p95_latency_ms": 188},
            "agent_results": {
                "business_control": response_payload(
                    "business_control",
                    {"baseline_peak_rps": 1346, "historical_avg_shaped_rps": 782},
                ),
                "demand_shaping": response_payload(
                    "demand_shaping",
                    {"send_window_minutes": 10, "peak_reduction_percent": 42},
                ),
            },
        }

        result, _ = logic.evaluate(context)

        self.assertEqual(result["forecast_variance_from_history"], -0.3)

    def test_infra_execution_pod_variance_from_history(self) -> None:
        logic = load_agent_logic("infra-execution")
        context = {
            "infra": {},
            "agent_results": {
                "traffic_forecast": response_payload(
                    "traffic_forecast",
                    {"required_app_pods": 28},
                ),
                "business_control": response_payload(
                    "business_control",
                    {"historical_avg_pods": 25.4},
                ),
            },
        }

        result, _ = logic.evaluate(context)

        self.assertEqual(result["historical_avg_pods"], 25.4)
        self.assertEqual(result["pod_variance_from_history"], 10.2)


if __name__ == "__main__":
    unittest.main()
