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
    spec = importlib.util.spec_from_file_location(f"test_{directory}_capacity_plan_v2", path)
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


def forecast_result() -> dict:
    return {
        "peak_rps_after": 1932,
        "required_app_pods": 69,
        "current_pods": 27,
        "scale_out_pods": 42,
        "estimated_p95_ms": 190,
        "candidate_forecasts": [
            {
                "label": "안정성 우선",
                "required_app_pods": 69,
                "scale_out_pods": 42,
                "estimated_p95_ms": 190,
                "peak_rps_after": 1932,
                "send_window_minutes": 10,
            },
            {
                "label": "균형",
                "required_app_pods": 64,
                "scale_out_pods": 37,
                "estimated_p95_ms": 189,
                "peak_rps_after": 1778,
                "send_window_minutes": 15,
            },
            {
                "label": "비용 우선",
                "required_app_pods": 61,
                "scale_out_pods": 34,
                "estimated_p95_ms": 189,
                "peak_rps_after": 1701,
                "send_window_minutes": 20,
            },
        ],
    }


def base_context() -> dict:
    return {
        "event": {"grade": "S"},
        "policy": {"approval_required": True},
        "signals": {
            "required_app_pods": 29,
            "eks_cost_usd": 31.2,
            "network_cost_usd": 8.1,
            "log_cost_usd": 3.4,
            "push_cost_usd": 7.6,
        },
        "infra": {"nodegroup_desired": 12, "nodegroup_max": 30},
        "cost_source": {"event_incremental_budget_usd": 95},
        "live": {"commands": {}},
        "agent_results": {
            "business_control": response_payload("business_control", {"grade": "S"}),
            "cluster_state": response_payload(
                "cluster_state",
                {
                    "scale_target_current_pods": 27,
                    "total_estimated_saving_usd": 0.14,
                    "idle_candidates": [
                        {
                            "namespace": "kyverno",
                            "deployment": "kyverno-admission-controller",
                            "current_replicas": 2,
                            "hpa_min": 1,
                            "reducible_replicas": 1,
                            "estimated_saving_usd": 0.14,
                            "risk": "low",
                        }
                    ],
                },
            ),
            "traffic_forecast": response_payload("traffic_forecast", forecast_result()),
            "bottleneck_capacity": response_payload(
                "bottleneck_capacity",
                {"ready_pods": 27, "pod_readiness_percent": 39.0, "bottleneck_risk": "critical"},
            ),
        },
    }


class InfraCostCapacityPlanV2Tests(unittest.TestCase):
    def test_infra_builds_candidate_capacity_plans(self) -> None:
        context = base_context()
        result, _ = load_agent_logic("infra-execution").evaluate(context)

        self.assertEqual(result["target_app_pods"], 69)
        self.assertEqual(result["scale_out_pods"], 42)
        self.assertEqual(len(result["candidate_capacity_plans"]), 3)
        self.assertEqual(result["candidate_capacity_plans"][0]["additional_nodes_required"], 6)

    def test_infra_includes_idle_resource_plan(self) -> None:
        context = base_context()
        result, _ = load_agent_logic("infra-execution").evaluate(context)

        self.assertEqual(result["idle_resource_plan"][0]["target_replicas"], 1)
        self.assertIn("reduce_idle_resources", result["approval_required_actions"])

    def test_infra_excludes_spot_for_grade_s_scale_target(self) -> None:
        context = base_context()
        result, _ = load_agent_logic("infra-execution").evaluate(context)

        self.assertFalse(result["spot_policy"]["spot_allowed_for_scale_target"])
        self.assertEqual(result["spot_policy"]["scale_target_capacity_type"], "on_demand")

    def test_cost_uses_infra_plan_for_candidate_net_costs(self) -> None:
        context = base_context()
        infra_result, _ = load_agent_logic("infra-execution").evaluate(context)
        context["agent_results"]["infra_execution"] = response_payload("infra_execution", infra_result)

        result, _ = load_agent_logic("cost").evaluate(context)

        self.assertEqual(result["estimated_cost_usd"], 93.33)
        self.assertEqual(result["idle_resource_saving_usd"], 0.14)
        self.assertEqual(result["net_cost_after_idle_reduction"], 93.19)
        self.assertEqual(result["candidate_costs"][0]["scale_out_pods"], 42)

    def test_nodegroup_capacity_check_uses_pod_density(self) -> None:
        context = base_context()
        result, _ = load_agent_logic("infra-execution").evaluate(context)

        self.assertEqual(result["nodegroup_capacity_check"]["additional_nodes_required"], 6)
        self.assertFalse(result["nodegroup_capacity_check"]["max_adjustment_required"])


if __name__ == "__main__":
    unittest.main()
