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


def context() -> dict:
    return {
        "policy": {"vip_immediate": True, "max_general_delay_minutes": 10},
        "business": {"vip_audience_count": 42000, "general_audience_count": 308000},
        "agent_results": {
            "business_control": response_payload(
                "business_control",
                {
                    "max_delay_minutes": 10,
                    "target_users": 350000,
                    "vip_audience_count": 42000,
                    "general_audience_count": 308000,
                },
            )
        },
    }


class DemandShapingV2Tests(unittest.TestCase):
    def test_no_longer_returns_traffic_or_pod_fields(self) -> None:
        result, _ = load_agent_logic("demand-shaping").evaluate(context())

        for field in ["peak_rps_after", "required_app_pods", "peak_reduction_percent"]:
            self.assertNotIn(field, result)

    def test_returns_three_sending_candidates(self) -> None:
        result, _ = load_agent_logic("demand-shaping").evaluate(context())

        self.assertEqual([item["label"] for item in result["candidates"]], ["안정성 우선", "균형", "비용 우선"])
        self.assertEqual([item["send_window_minutes"] for item in result["candidates"]], [10, 15, 20])

    def test_calculates_general_users_per_minute(self) -> None:
        result, _ = load_agent_logic("demand-shaping").evaluate(context())

        self.assertEqual(result["per_minute_general"], 30800.0)

    def test_calculates_general_users_per_second(self) -> None:
        result, _ = load_agent_logic("demand-shaping").evaluate(context())

        self.assertAlmostEqual(result["per_second_general"], 513.3, places=1)


if __name__ == "__main__":
    unittest.main()
