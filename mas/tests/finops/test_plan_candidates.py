from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MAS_ROOT = Path(__file__).resolve().parents[2]
if str(MAS_ROOT) not in sys.path:
    sys.path.insert(0, str(MAS_ROOT))

from contracts.models import AgentResponse, AgentStatus, PlanCandidate


FINOPS_ROOT = MAS_ROOT / "pods" / "finops"
AGENTS_PATH = str(FINOPS_ROOT / "agents")


def prefer_agents_app_package() -> None:
    for path in list(sys.path):
        normalized = path.replace("\\", "/")
        if normalized.endswith("/mas/pods/finops/orchestrator") or normalized.endswith("/mas/pods/finops/ui"):
            sys.path.remove(path)
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            sys.modules.pop(key, None)
    if AGENTS_PATH in sys.path:
        sys.path.remove(AGENTS_PATH)
    sys.path.insert(0, AGENTS_PATH)


prefer_agents_app_package()

from app.agent_support import AGENT_NAMES, standard_response  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runtime = load_module(
    "plan_candidate_runtime_test",
    FINOPS_ROOT / "orchestrator" / "app" / "agent_runtime.py",
)


def load_agent(directory: str):
    return load_module(
        f"candidate_{directory}_logic",
        FINOPS_ROOT / directory / "app" / "agent_logic.py",
    )


def response_payload(
    agent_key: str,
    result: dict,
    *,
    status: AgentStatus = AgentStatus.COMPLETED,
    confidence: float = 0.8,
) -> dict:
    return AgentResponse(
        status=status,
        agent_key=agent_key,
        agent_name=AGENT_NAMES.get(agent_key, agent_key),
        result=result,
        message="ok",
        evidence=[],
        data_requests=[],
        confidence=confidence,
        warnings=[],
        reasoning_source="rule",
    ).model_dump(mode="json")


def shaping_context() -> dict:
    return {
        "policy": {
            "vip_immediate": True,
            "max_general_delay_minutes": 10,
        },
        "business": {
            "vip_audience_count": 42000,
            "general_audience_count": 308000,
            "crm_segment": "test",
        },
        "agent_results": {
            "business_control": response_payload(
                "business_control",
                {
                    "max_delay_minutes": 10,
                    "target_users": 350000,
                },
            )
        },
    }


def candidate_pipeline() -> tuple[dict, dict, dict]:
    demand = load_agent("demand-shaping")
    traffic = load_agent("traffic-forecast")
    cost_agent = load_agent("cost")
    context = shaping_context()
    shaping, _ = demand.evaluate(context)
    context["agent_results"]["demand_shaping"] = response_payload(
        "demand_shaping", shaping
    )
    context.update(
        {
            "signals": {
                "baseline_peak_rps": 1420,
                "required_app_pods": 29,
                "eks_cost_usd": 31.2,
                "network_cost_usd": 8.1,
                "log_cost_usd": 3.4,
                "push_cost_usd": 7.6,
            },
            "traffic": {
                "prometheus_rps": 1420,
                "hpa_desired_replicas": 29,
                "p95_latency_ms": 188,
            },
            "live": {"commands": {}},
            "broker_results": {},
        }
    )
    forecast, _ = traffic.evaluate(context)
    context["agent_results"]["traffic_forecast"] = response_payload(
        "traffic_forecast", forecast
    )
    context["agent_results"]["infra_execution"] = response_payload(
        "infra_execution", {"target_app_pods": 29}
    )
    context["cost_source"] = {"event_incremental_budget_usd": 95}
    cost, _ = cost_agent.evaluate(context)
    return shaping, forecast, cost


def complete_quality_context() -> dict:
    results = {
        key: response_payload(key, {"ok": True})
        for key, _ in runtime.AGENT_SEQUENCE
    }
    results["policy_guardrail"] = response_payload(
        "policy_guardrail", {"allowed": ["scale_out"], "proceed": True}
    )
    return {"agent_results": results}


class PlanCandidateTests(unittest.TestCase):
    def test_01_demand_shaping_creates_three_candidates(self) -> None:
        result, _ = load_agent("demand-shaping").evaluate(shaping_context())
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(
            [item["label"] for item in result["candidates"]],
            ["안정성 우선", "균형", "비용 우선"],
        )

    def test_02_first_candidate_preserves_single_fields(self) -> None:
        result, _ = load_agent("demand-shaping").evaluate(shaping_context())
        first = result["candidates"][0]
        self.assertEqual(result["send_window_minutes"], first["push_window_minutes"])
        self.assertEqual(result["per_minute_general"], first["per_minute_general"])
        self.assertEqual(result["per_second_general"], first["per_second_general"])
        self.assertNotIn("peak_reduction_percent", result)

    def test_03_traffic_calculates_candidate_forecasts(self) -> None:
        _, forecast, _ = candidate_pipeline()
        candidates = forecast["candidate_forecasts"]
        self.assertEqual([item["peak_rps_after"] for item in candidates], [1932, 1778, 1701])
        self.assertEqual(candidates[0]["vip_peak_rps"], 1470)
        self.assertEqual(candidates[0]["general_peak_rps"], 462)
        self.assertEqual(candidates[0]["required_app_pods"], 69)
        self.assertLess(candidates[1]["required_app_pods"], candidates[0]["required_app_pods"])

    def test_04_cost_does_not_hide_budget_overrun(self) -> None:
        _, forecast, _ = candidate_pipeline()
        context = shaping_context()
        context.update(
            {
                "signals": {
                    "eks_cost_usd": 31.2,
                    "network_cost_usd": 8.1,
                    "log_cost_usd": 3.4,
                    "push_cost_usd": 7.6,
                },
                "cost_source": {"event_incremental_budget_usd": 40},
            }
        )
        context["agent_results"].update(
            {
                "traffic_forecast": response_payload("traffic_forecast", forecast),
                "infra_execution": response_payload(
                    "infra_execution", {"target_app_pods": 29}
                ),
            }
        )
        result, _ = load_agent("cost").evaluate(context)
        self.assertEqual(result["total"], 50.3)
        self.assertEqual(result["estimated_cost_usd"], 50.3)
        self.assertTrue(result["budget_exceeded"])

    def test_05_cost_calculates_each_candidate(self) -> None:
        _, _, cost = candidate_pipeline()
        self.assertEqual(len(cost["candidate_costs"]), 3)
        self.assertEqual(cost["candidate_costs"][0]["estimated_cost_usd"], 93.33)
        self.assertLess(
            cost["candidate_costs"][1]["estimated_cost_usd"],
            cost["candidate_costs"][0]["estimated_cost_usd"],
        )

    def test_06_budget_exceeded_candidate_scores_zero(self) -> None:
        candidate = PlanCandidate(
            label="over",
            push_window_minutes=10,
            required_pods=29,
            estimated_cost_usd=100,
            estimated_p95_ms=180,
            risk_level="high",
            budget_exceeded=True,
            policy_violations=[],
        )
        self.assertEqual(
            runtime.score_candidate(
                candidate,
                runtime.DEFAULT_CANDIDATE_WEIGHTS,
                {"max_pods": 40, "max_cost_usd": 80, "max_p95_ms": 200},
            ),
            0.0,
        )

    def test_07_policy_violation_candidate_scores_zero(self) -> None:
        candidate = PlanCandidate(
            label="blocked",
            push_window_minutes=10,
            required_pods=29,
            estimated_cost_usd=50,
            estimated_p95_ms=180,
            risk_level="high",
            budget_exceeded=False,
            policy_violations=["policy_guardrail_blocked"],
        )
        self.assertEqual(
            runtime.score_candidate(
                candidate,
                runtime.DEFAULT_CANDIDATE_WEIGHTS,
                {"max_pods": 40, "max_cost_usd": 80, "max_p95_ms": 200},
            ),
            0.0,
        )

    def test_08_candidates_are_sorted_and_recommended(self) -> None:
        shaping, forecast, cost = candidate_pipeline()
        context = {
            "policy": {"max_general_delay_minutes": 10},
            "constraints": {"max_pods": 40, "max_p95_ms": 200},
        }
        candidates, recommended, _ = runtime.build_plan_candidates(
            context,
            shaping,
            forecast,
            cost,
            {"allowed": ["scale_out"]},
            {"nodegroup_max": 40},
        )
        self.assertEqual(candidates, sorted(candidates, key=lambda item: item.score, reverse=True))
        self.assertIsNotNone(recommended)
        self.assertEqual(recommended.score, candidates[0].score)

    def test_09_missing_agents_are_reported(self) -> None:
        candidate = PlanCandidate(
            label="valid", push_window_minutes=10, required_pods=10,
            estimated_cost_usd=10, estimated_p95_ms=100, risk_level="low",
            budget_exceeded=False, policy_violations=[], score=0.5,
        )
        gate, _ = runtime.evaluate_quality_gate(
            {"agent_results": {}}, [candidate], candidate, 20
        )
        self.assertTrue(any(issue.startswith("missing_agents:") for issue in gate["issues"]))
        incomplete_plan = runtime.build_final_plan(
            {
                "event": {
                    "event_id": "missing",
                    "title": "Missing agents",
                    "grade": "S",
                    "target_users": 1,
                    "scheduled_at": "08:30 KST",
                },
                "business": {},
                "policy": {"max_general_delay_minutes": 10},
                "policy_source": {},
                "agent_results": {},
            }
        )
        self.assertEqual(runtime.plan_status(incomplete_plan), "requires_review")

    def test_10_blocked_failed_and_low_confidence_are_reported(self) -> None:
        context = complete_quality_context()
        context["agent_results"]["policy_guardrail"] = response_payload(
            "policy_guardrail", {"ok": True}, status=AgentStatus.BLOCKED
        )
        context["agent_results"]["postmortem_learning"] = response_payload(
            "postmortem_learning", {"ok": True}, status=AgentStatus.FAILED
        )
        for key in ["business_control", "demand_shaping", "traffic_forecast"]:
            context["agent_results"][key] = response_payload(
                key, {"ok": True}, confidence=0.4
            )
        candidate = PlanCandidate(
            label="valid", push_window_minutes=10, required_pods=10,
            estimated_cost_usd=10, estimated_p95_ms=100, risk_level="low",
            budget_exceeded=False, policy_violations=[], score=0.5,
        )
        gate, failed = runtime.evaluate_quality_gate(context, [candidate], candidate, 20)
        self.assertTrue(any(issue.startswith("has_blocked_agents:") for issue in gate["issues"]))
        self.assertTrue(any(issue.startswith("has_failed_agents:") for issue in gate["issues"]))
        self.assertTrue(any(issue.startswith("low_confidence:") for issue in gate["issues"]))
        self.assertEqual(failed, ["postmortem_learning"])

    def test_11_no_valid_candidate_fails_gate(self) -> None:
        context = complete_quality_context()
        candidate = PlanCandidate(
            label="invalid", push_window_minutes=10, required_pods=10,
            estimated_cost_usd=30, estimated_p95_ms=100, risk_level="high",
            budget_exceeded=True, policy_violations=[], score=0.0,
        )
        gate, _ = runtime.evaluate_quality_gate(context, [candidate], None, 20)
        self.assertIn("no_valid_candidate", gate["issues"])
        self.assertFalse(gate["passed"])

    def test_12_single_result_falls_back_to_default_candidate(self) -> None:
        context = {"policy": {"max_general_delay_minutes": 10}}
        candidates, _, _ = runtime.build_plan_candidates(
            context,
            {"send_window_minutes": 10},
            {"required_app_pods": 29, "p95_latency_ms": 188},
            {"total": 50.3, "event_incremental_budget_usd": 95},
            {"allowed": ["scale_out"]},
            {"nodegroup_max": 40},
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].label, "기본 계획")

    def test_13_plan_status_uses_quality_gate(self) -> None:
        self.assertEqual(
            runtime.plan_status({"quality_gate_result": {"passed": True}}),
            "plan_ready",
        )
        self.assertEqual(
            runtime.plan_status({"quality_gate_result": {"passed": False}}),
            "requires_review",
        )

    def test_14_observer_and_fallback_are_not_required_workflow_agents(self) -> None:
        sequence = [key for key, _ in runtime.AGENT_SEQUENCE]

        self.assertNotIn("observer", sequence)
        self.assertNotIn("fallback", sequence)
        self.assertIn("policy_guardrail", sequence)

    def test_15_static_agent_scenario_regression(self) -> None:
        sequence = [key for key, _ in runtime.AGENT_SEQUENCE]
        context = {
            "event": {
                "event_id": "test", "title": "Test", "grade": "S",
                "target_users": 350000, "scheduled_at": "08:30 KST",
            },
            "policy": {
                "approval_required": True, "vip_immediate": True,
                "max_general_delay_minutes": 10,
            },
            "business": {
                "vip_audience_count": 42000,
                "general_audience_count": 308000,
                "crm_segment": "test",
            },
            "signals": {
                "baseline_peak_rps": 1420, "required_app_pods": 29,
                "expected_value_usd": 4200, "eks_cost_usd": 31.2,
                "network_cost_usd": 8.1, "log_cost_usd": 3.4,
                "push_cost_usd": 7.6,
            },
            "traffic": {
                "prometheus_rps": 1420, "hpa_desired_replicas": 29,
                "p95_latency_ms": 188,
            },
            "infra": {
                "rds_cpu_percent": 68, "redis_cache_hit_ratio_percent": 91,
                "nodegroup_max": 40,
            },
            "cost_source": {"event_incremental_budget_usd": 95},
            "policy_source": {
                "allowed_actions": ["scale_out"], "forbidden_actions": []
            },
            "live": {"commands": {}}, "agent_results": {}, "broker_results": {},
        }
        for key in sequence:
            module = load_agent(key.replace("_", "-"))
            evaluation = module.evaluate(context)
            if isinstance(evaluation, AgentResponse):
                response = evaluation
            else:
                result, message = evaluation
                response = AgentResponse.model_validate(
                    standard_response(
                        key, AGENT_NAMES[key], result, message,
                        context["agent_results"], "rule",
                    )
                )
            self.assertEqual(response.status, AgentStatus.COMPLETED)
            context["agent_results"][key] = response.model_dump(mode="json")

        plan = runtime.build_final_plan(context)
        self.assertEqual(plan["peak_rps_after"], 1932)
        self.assertEqual(plan["required_app_pods"], 69)
        self.assertEqual(len(plan["plan_candidates"]), 3)
        self.assertTrue(plan["report"]["operations"]["fallback"]["vip_only"])
        self.assertTrue(plan["quality_gate_result"]["passed"])
        self.assertEqual(runtime.plan_status(plan), "plan_ready")


if __name__ == "__main__":
    unittest.main()
