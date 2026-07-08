from __future__ import annotations

import importlib.util
import os
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


def shaping_candidates() -> list[dict]:
    return [
        {
            "label": "안정성 우선",
            "send_window_minutes": 10,
            "push_window_minutes": 10,
            "vip_send_mode": "즉시 발송",
            "general_send_mode": "10분 균등 분산",
            "per_minute_general": 30800.0,
            "per_second_general": 513.3,
            "vip_count": 42000,
            "general_count": 308000,
        },
        {
            "label": "균형",
            "send_window_minutes": 15,
            "push_window_minutes": 15,
            "vip_send_mode": "즉시 발송",
            "general_send_mode": "15분 균등 분산",
            "per_minute_general": 20533.3,
            "per_second_general": 342.2,
            "vip_count": 42000,
            "general_count": 308000,
        },
        {
            "label": "비용 우선",
            "send_window_minutes": 20,
            "push_window_minutes": 20,
            "vip_send_mode": "즉시 발송",
            "general_send_mode": "20분 균등 분산",
            "per_minute_general": 15400.0,
            "per_second_general": 256.7,
            "vip_count": 42000,
            "general_count": 308000,
        },
    ]


def context_with_candidates() -> dict:
    return {
        "policy": {"max_general_delay_minutes": 10},
        "signals": {"baseline_peak_rps": 1346, "required_app_pods": 29},
        "traffic": {"p95_latency_ms": 188},
        "live": {"commands": {}},
        "broker_results": {},
        "agent_results": {
            "business_control": response_payload(
                "business_control",
                {"baseline_peak_rps": 1346, "historical_avg_shaped_rps": 782},
            ),
            "cluster_state": response_payload(
                "cluster_state",
                {"scale_target_current_pods": 27},
            ),
            "demand_shaping": response_payload(
                "demand_shaping",
                {"send_window_minutes": 10, "candidates": shaping_candidates()},
            ),
        },
    }


class TrafficForecastV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "APP_OPEN_RATE_VIP": "0.35",
                "APP_OPEN_RATE_GENERAL": "0.30",
                "REQUESTS_PER_OPEN": "3",
                "VIP_OPEN_WINDOW_SECONDS": "30",
                "RPS_PER_POD": "28.0",
            },
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_calculates_vip_peak_rps(self) -> None:
        result, _ = load_agent_logic("traffic-forecast").evaluate(context_with_candidates())

        self.assertEqual(result["vip_peak_rps"], 1470)

    def test_calculates_general_peak_rps(self) -> None:
        result, _ = load_agent_logic("traffic-forecast").evaluate(context_with_candidates())

        self.assertEqual(result["general_peak_rps"], 462)

    def test_calculates_total_peak_rps(self) -> None:
        result, _ = load_agent_logic("traffic-forecast").evaluate(context_with_candidates())

        self.assertEqual(result["peak_rps_after"], 1932)

    def test_calculates_required_pods_and_scale_out(self) -> None:
        result, _ = load_agent_logic("traffic-forecast").evaluate(context_with_candidates())

        self.assertEqual(result["required_app_pods"], 69)
        self.assertEqual(result["current_pods"], 27)
        self.assertEqual(result["scale_out_pods"], 42)

    def test_falls_back_when_demand_shaping_has_no_candidates(self) -> None:
        context = context_with_candidates()
        context["agent_results"]["demand_shaping"] = response_payload(
            "demand_shaping",
            {"send_window_minutes": 10, "peak_reduction_percent": 42},
        )

        result, _ = load_agent_logic("traffic-forecast").evaluate(context)

        self.assertEqual(result["based_on"], "fallback_baseline_reduction")
        self.assertEqual(result["peak_rps_after"], 780)


if __name__ == "__main__":
    unittest.main()
