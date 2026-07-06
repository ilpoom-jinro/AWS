from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


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
    spec = importlib.util.spec_from_file_location(f"test_{directory}_cloudwatch_logic", path)
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


class CloudWatchIntegrationTests(unittest.TestCase):
    def test_collect_rds_metrics_returns_error_dict_on_boto3_failure(self) -> None:
        logic = load_agent_logic("cluster-state")
        with patch.dict(sys.modules, {"boto3": None}):
            result = logic.collect_rds_metrics()

        self.assertIn("financial-service-db", result)
        self.assertEqual(result["financial-service-db"]["source"], "cloudwatch_failed")

    def test_collect_rds_metrics_includes_cpu_when_cloudwatch_succeeds(self) -> None:
        logic = load_agent_logic("cluster-state")
        cloudwatch = MagicMock()
        cloudwatch.get_metric_statistics.side_effect = [
            {"Datapoints": [{"Timestamp": datetime.now(timezone.utc), "Average": 68.34}]},
            {"Datapoints": [{"Timestamp": datetime.now(timezone.utc), "Average": 12.2}]},
            {"Datapoints": []},
            {"Datapoints": []},
        ]
        boto3 = MagicMock()
        boto3.client.return_value = cloudwatch
        with patch.dict(sys.modules, {"boto3": boto3}):
            result = logic.collect_rds_metrics()

        self.assertEqual(result["financial-service-db"]["cpu_percent"], 68.3)
        self.assertEqual(result["financial-service-db"]["connections"], 12)
        self.assertEqual(result["financial-service-db"]["source"], "cloudwatch")

    def test_bottleneck_falls_back_to_seed_when_cloudwatch_failed(self) -> None:
        logic = load_agent_logic("bottleneck-capacity")
        context = {
            "signals": {"db_cpu_percent": 68, "cache_hit_ratio_percent": 91},
            "infra": {},
            "agent_results": {
                "cluster_state": response_payload(
                    "cluster_state",
                    {
                        "rds_cpu_percent": None,
                        "rds_connections": None,
                        "rds_source": "cloudwatch_failed",
                    },
                ),
                "traffic_forecast": response_payload(
                    "traffic_forecast",
                    {"peak_rps_after": 823, "required_app_pods": 29},
                ),
            },
        }

        result, _ = logic.evaluate(context)

        self.assertEqual(result["rds_data_source"], "cloudwatch_failed")
        self.assertEqual(result["data_quality"], "cloudwatch_failed_seed_fallback")
        self.assertEqual(result["db_cpu"], "68%")

    def test_bottleneck_sets_cloudwatch_data_quality(self) -> None:
        logic = load_agent_logic("bottleneck-capacity")
        context = {
            "signals": {"cache_hit_ratio_percent": 91},
            "infra": {},
            "agent_results": {
                "cluster_state": response_payload(
                    "cluster_state",
                    {
                        "rds_cpu_percent": 66.5,
                        "rds_connections": 22,
                        "rds_source": "cloudwatch",
                    },
                ),
                "traffic_forecast": response_payload(
                    "traffic_forecast",
                    {"peak_rps_after": 823, "required_app_pods": 29},
                ),
            },
        }

        result, _ = logic.evaluate(context)

        self.assertEqual(result["rds_data_source"], "cloudwatch")
        self.assertEqual(result["data_quality"], "realtime_cloudwatch")


if __name__ == "__main__":
    unittest.main()
