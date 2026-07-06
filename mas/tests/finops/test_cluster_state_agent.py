from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


cluster_logic = load_module(
    "cluster_state_agent_logic",
    ROOT / "mas" / "pods" / "finops" / "cluster-state" / "app" / "agent_logic.py",
)
business_logic = load_module(
    "business_control_agent_logic",
    ROOT / "mas" / "pods" / "finops" / "business-control" / "app" / "agent_logic.py",
)


class ClusterStateAgentTests(TestCase):
    def test_collect_all_deployments_parses_kubectl_json(self) -> None:
        payload = {
            "items": [
                {
                    "metadata": {"namespace": "payments", "name": "api"},
                    "spec": {"replicas": 3},
                    "status": {"readyReplicas": 2, "availableReplicas": 2},
                }
            ]
        }
        completed = SimpleNamespace(stdout=json.dumps(payload))
        with patch.object(cluster_logic.subprocess, "run", return_value=completed):
            deployments = cluster_logic.collect_all_deployments()

        self.assertEqual(
            deployments,
            [
                {
                    "namespace": "payments",
                    "name": "api",
                    "current_replicas": 3,
                    "ready_replicas": 2,
                    "available_replicas": 2,
                }
            ],
        )

    def test_collect_hpa_info_uses_namespace_name_key(self) -> None:
        payload = {
            "items": [
                {
                    "metadata": {"namespace": "payments", "name": "api"},
                    "spec": {"minReplicas": 2, "maxReplicas": 8},
                    "status": {"currentReplicas": 5},
                }
            ]
        }
        completed = SimpleNamespace(stdout=json.dumps(payload))
        with patch.object(cluster_logic.subprocess, "run", return_value=completed):
            hpa = cluster_logic.collect_hpa_info()

        self.assertEqual(hpa["payments/api"], {"min": 2, "max": 8, "current": 5})

    def test_evaluate_detects_idle_resources_when_current_above_hpa_min(self) -> None:
        with patch.object(
            cluster_logic,
            "collect_all_deployments",
            return_value=[
                {"namespace": "analytics", "name": "worker", "current_replicas": 4, "ready_replicas": 4},
                {"namespace": "finops-mas", "name": "ui", "current_replicas": 2, "ready_replicas": 2},
            ],
        ), patch.object(
            cluster_logic,
            "collect_hpa_info",
            return_value={"analytics/worker": {"min": 1, "max": 5, "current": 4}},
        ), patch.object(
            cluster_logic,
            "collect_spot_prices",
            return_value={"m5.xlarge": 0.15},
        ):
            result, _ = cluster_logic.evaluate({})

        self.assertEqual(result["idle_candidate_count"], 1)
        self.assertEqual(result["idle_candidates"][0]["reducible_replicas"], 3)
        self.assertEqual(result["total_event_related_pods"], 2)

    def test_evaluate_calculates_estimated_saving(self) -> None:
        with patch.object(
            cluster_logic,
            "collect_all_deployments",
            return_value=[
                {"namespace": "analytics", "name": "worker", "current_replicas": 3, "ready_replicas": 3},
            ],
        ), patch.object(
            cluster_logic,
            "collect_hpa_info",
            return_value={"analytics/worker": {"min": 1, "max": 5, "current": 3}},
        ), patch.object(
            cluster_logic,
            "collect_spot_prices",
            return_value={"m5.xlarge": 0.15},
        ):
            result, _ = cluster_logic.evaluate({})

        self.assertEqual(result["total_reducible_pods"], 2)
        self.assertEqual(result["total_estimated_saving_usd"], 0.6)

    def test_business_control_includes_event_history_summary(self) -> None:
        context = {
            "event": {"event_id": "fomc-briefing", "title": "FOMC", "grade": "S", "target_users": 350000},
            "policy": {"approval_required": True, "max_general_delay_minutes": 10},
            "business": {
                "vip_audience_count": 42000,
                "general_audience_count": 308000,
                "push_channel": "mobile-push",
                "campaign_importance": "tier-0-market-moving",
                "calendar_source": "business_calendar",
            },
        }
        history = [
            {
                "event_date": "2025-11-07",
                "actual_peak_rps": 1380,
                "actual_pods_used": 26,
                "actual_cost_usd": 47.2,
                "actual_p95_ms": 181,
            },
            {
                "event_date": "2025-09-18",
                "actual_peak_rps": 1450,
                "actual_pods_used": 31,
                "actual_cost_usd": 53.1,
                "actual_p95_ms": 195,
            },
        ]
        with patch.object(business_logic, "_query_event_history", return_value=history):
            result, _ = business_logic.evaluate(context)

        self.assertEqual(result["historical_event_count"], 2)
        self.assertEqual(result["historical_avg_peak_rps"], 1415)
        self.assertEqual(result["historical_avg_pods"], 28.5)
        self.assertEqual(len(result["historical_events"]), 2)
