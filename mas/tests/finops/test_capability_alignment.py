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


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_agent_support():
    prefer_agents_app_package()
    try:
        return load_module(
            "capability_alignment_agent_support_test",
            FINOPS_ROOT / "agents" / "app" / "agent_support.py",
        )
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


def load_agent_logic(directory: str):
    prefer_agents_app_package()
    try:
        return load_module(
            f"capability_alignment_{directory}_logic_test",
            FINOPS_ROOT / directory / "app" / "agent_logic.py",
        )
    finally:
        if AGENTS_PATH in sys.path:
            sys.path.remove(AGENTS_PATH)


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


class CapabilityAlignmentTests(unittest.TestCase):
    def test_all_agents_are_registered_in_agent_capabilities(self) -> None:
        support = load_agent_support()

        self.assertEqual(set(support.AGENT_CAPABILITIES), EXPECTED_AGENT_KEYS)

    def test_traffic_p95_latency_resolves_as_estimated_p95_alias(self) -> None:
        support = load_agent_support()

        resolved = support.resolve_fields_from_context(
            "traffic_forecast",
            ["estimated_p95_ms"],
            {"p95_latency_ms": 188.0},
        )

        self.assertEqual(resolved, {"estimated_p95_ms": 188.0})

    def test_bottleneck_db_cpu_resolves_from_actual_result_key(self) -> None:
        support = load_agent_support()

        resolved = support.resolve_fields_from_context(
            "bottleneck_capacity",
            ["db_cpu", "cache_hit_ratio"],
            {"db_cpu": "75%", "cache_hit_ratio": "72%"},
        )

        self.assertEqual(resolved, {"db_cpu": "75%", "cache_hit_ratio": "72%"})

    def test_observer_returns_numeric_threshold_fields(self) -> None:
        observer = load_agent_logic("observer")
        context = {
            "signals": {},
            "agent_results": {
                "traffic_forecast": agent_response(
                    "traffic_forecast",
                    {"peak_rps_after": 823, "required_app_pods": 29},
                ),
                "policy_guardrail": agent_response(
                    "policy_guardrail",
                    {"approval_required": True, "allowed": ["scale_out"]},
                ),
            },
        }

        result, _message = observer.evaluate(context)

        self.assertEqual(result["scale_down_rps_threshold"], 576)
        self.assertEqual(result["alert_rps_threshold"], 987)
        self.assertEqual(result["monitoring_interval_seconds"], 30)

    def test_capability_docs_match_registered_fields_for_core_agents(self) -> None:
        support = load_agent_support()
        checks = {
            "traffic-forecast": ("traffic_forecast", ["peak_rps_after", "required_app_pods", "estimated_p95_ms"]),
            "cost": ("cost", ["total", "estimated_cost_usd", "event_incremental_budget_usd"]),
            "observer": ("observer", ["scale_down_rps_threshold", "alert_rps_threshold", "monitoring_interval_seconds"]),
        }

        for directory, (agent_key, fields) in checks.items():
            capability_text = (FINOPS_ROOT / directory / "capability.md").read_text(
                encoding="utf-8"
            )
            registered = support.AGENT_CAPABILITIES[agent_key]["fields"]
            for field in fields:
                with self.subTest(agent_key=agent_key, field=field):
                    self.assertIn(f"`{field}`", capability_text)
                    self.assertIn(field, registered)

    def test_static_agent_sequence_still_produces_required_results(self) -> None:
        context = {
            "event": {
                "event_id": "fomc-briefing",
                "title": "FOMC briefing",
                "grade": "S",
                "target_users": 350000,
            },
            "policy": {
                "approval_required": True,
                "max_general_delay_minutes": 10,
                "vip_immediate": True,
            },
            "business": {
                "vip_audience_count": 42000,
                "general_audience_count": 308000,
                "push_channel": "mobile_push",
                "campaign_importance": "high",
            },
            "signals": {
                "baseline_peak_rps": 1420,
                "required_app_pods": 29,
                "expected_value_usd": 4200,
            },
            "traffic": {
                "prometheus_rps": 1420,
                "hpa_desired_replicas": 29,
                "p95_latency_ms": 188.0,
            },
            "infra": {
                "rds_cpu_percent": 68,
                "redis_cache_hit_ratio_percent": 91,
                "eks_deployment_replicas": 14,
                "ready_pods": 14,
            },
            "cost_source": {"event_incremental_budget_usd": 95},
            "policy_source": {"allowed_actions": ["scale_out", "prewarm"]},
            "agent_results": {},
        }

        sequence = [
            ("business-control", "business_control"),
            ("demand-shaping", "demand_shaping"),
            ("traffic-forecast", "traffic_forecast"),
            ("bottleneck-capacity", "bottleneck_capacity"),
            ("infra-execution", "infra_execution"),
            ("cost", "cost"),
            ("unit-economics", "unit_economics"),
            ("policy-guardrail", "policy_guardrail"),
            ("observer", "observer"),
            ("fallback", "fallback"),
            ("postmortem-learning", "postmortem_learning"),
        ]

        for directory, agent_key in sequence:
            module = load_agent_logic(directory)
            output = module.evaluate(context)
            if isinstance(output, AgentResponse):
                response = output.model_dump(mode="json")
            else:
                result, _message = output
                response = agent_response(agent_key, result)
            context["agent_results"][agent_key] = response

        self.assertIn("scale_down_rps_threshold", context["agent_results"]["observer"]["result"])
        self.assertEqual(context["agent_results"]["traffic_forecast"]["result"]["required_app_pods"], 29)
        self.assertEqual(context["agent_results"]["cost"]["result"]["estimated_cost_usd"], 50.3)


if __name__ == "__main__":
    unittest.main()
