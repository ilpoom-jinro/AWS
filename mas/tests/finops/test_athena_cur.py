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
    spec = importlib.util.spec_from_file_location(f"test_{directory}_athena_logic", path)
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


class AthenaCurTests(unittest.TestCase):
    def test_query_cur_via_athena_returns_none_on_boto3_failure(self) -> None:
        logic = load_agent_logic("cost")
        with patch.dict(sys.modules, {"boto3": None}):
            self.assertIsNone(logic.query_cur_via_athena("2026", "7"))

    def test_cost_agent_uses_seed_fallback_when_athena_returns_none(self) -> None:
        logic = load_agent_logic("cost")
        context = {
            "signals": {
                "eks_cost_usd": 31.2,
                "network_cost_usd": 8.1,
                "log_cost_usd": 3.4,
                "push_cost_usd": 7.6,
            },
            "cost_source": {"event_incremental_budget_usd": 95.0},
            "agent_results": {
                "infra_execution": response_payload("infra_execution", {"target_app_pods": 29}),
                "traffic_forecast": response_payload("traffic_forecast", {"candidate_forecasts": []}),
                "cluster_state": response_payload("cluster_state", {"total_estimated_saving_usd": 0}),
            },
        }

        with patch.object(logic, "query_cur_via_athena", return_value=None):
            result, _ = logic.evaluate(context)

        self.assertEqual(result["cost_data_source"], "seed_fallback")
        self.assertIn("warnings", result)

    def test_cost_data_source_can_be_athena_cur(self) -> None:
        logic = load_agent_logic("cost")
        context = {
            "signals": {
                "eks_cost_usd": 31.2,
                "network_cost_usd": 8.1,
                "log_cost_usd": 3.4,
                "push_cost_usd": 7.6,
            },
            "cost_source": {"event_incremental_budget_usd": 95.0},
            "agent_results": {
                "infra_execution": response_payload("infra_execution", {"target_app_pods": 29}),
                "traffic_forecast": response_payload("traffic_forecast", {"candidate_forecasts": []}),
                "cluster_state": response_payload("cluster_state", {"total_estimated_saving_usd": 0}),
            },
        }
        cur_data = {
            "total_cost": 123.45,
            "eks_cost": 55.0,
            "ec2_cost": 44.0,
            "rds_cost": 24.45,
            "source": "athena_cur",
        }

        with patch.object(logic, "query_cur_via_athena", return_value=cur_data):
            result, _ = logic.evaluate(context)

        self.assertEqual(result["cost_data_source"], "athena_cur")
        self.assertEqual(result["cur_rds_cost"], 24.45)


if __name__ == "__main__":
    unittest.main()
