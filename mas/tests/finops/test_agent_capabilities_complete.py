from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MAS_ROOT = Path(__file__).resolve().parents[2]
if str(MAS_ROOT) not in sys.path:
    sys.path.insert(0, str(MAS_ROOT))


FINOPS_ROOT = MAS_ROOT / "pods" / "finops"
AGENTS_PATH = str(FINOPS_ROOT / "agents")
AGENTS_APP = FINOPS_ROOT / "agents" / "app"

EXPECTED_AGENT_KEYS = {
    "cluster_state",
    "business_control",
    "demand_shaping",
    "traffic_forecast",
    "bottleneck_capacity",
    "infra_execution",
    "cost",
    "unit_economics",
    "policy_guardrail",
    "observer",
    "fallback",
    "postmortem_learning",
}


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


def load_agent_support():
    prefer_agents_app_package()
    try:
        spec = importlib.util.spec_from_file_location(
            "agent_capabilities_complete_support_test",
            AGENTS_APP / "agent_support.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


class AgentCapabilitiesCompleteTests(unittest.TestCase):
    def test_all_agents_are_registered(self) -> None:
        support = load_agent_support()

        self.assertEqual(set(support.AGENT_CAPABILITIES), EXPECTED_AGENT_KEYS)

    def test_traffic_forecast_contains_observability_and_candidate_fields(self) -> None:
        support = load_agent_support()
        fields = support.AGENT_CAPABILITIES["traffic_forecast"]["fields"]

        for field in [
            "candidate_forecasts",
            "p95_latency_ms",
            "alb_request_count_5m",
            "queue_depth",
            "hpa_current_replicas",
        ]:
            self.assertIn(field, fields)

    def test_infra_execution_contains_capacity_fields(self) -> None:
        support = load_agent_support()
        fields = support.AGENT_CAPABILITIES["infra_execution"]["fields"]

        for field in [
            "prewarm_at",
            "nodegroup_desired",
            "nodegroup_max",
            "current_app_pods",
            "deployment_ready_replicas",
        ]:
            self.assertIn(field, fields)

    def test_each_agent_has_at_least_one_field(self) -> None:
        support = load_agent_support()

        empty_agents = [
            agent_key
            for agent_key, capability in support.AGENT_CAPABILITIES.items()
            if not capability.get("fields")
        ]

        self.assertEqual(empty_agents, [])

    def test_filter_allows_traffic_candidate_forecasts(self) -> None:
        support = load_agent_support()

        filtered = support.filter_required_fields_by_capability(
            "traffic_forecast",
            ["candidate_forecasts"],
        )

        self.assertEqual(filtered, ["candidate_forecasts"])

    def test_filter_allows_infra_nodegroup_fields(self) -> None:
        support = load_agent_support()

        filtered = support.filter_required_fields_by_capability(
            "infra_execution",
            ["nodegroup_desired", "nodegroup_max"],
        )

        self.assertEqual(filtered, ["nodegroup_desired", "nodegroup_max"])


if __name__ == "__main__":
    unittest.main()
