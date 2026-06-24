from __future__ import annotations

import sys
import unittest
from pathlib import Path


MAS_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_APP = MAS_ROOT / "pods" / "finops" / "orchestrator" / "app"
sys.path.insert(0, str(ORCHESTRATOR_APP))
import dev_workflow_support as main  # noqa: E402

AGENT_SEQUENCE = [
    ("business_control", "Business Control Agent"),
    ("traffic_forecast", "Traffic Forecast Agent"),
]


class DevWorkflowApiTests(unittest.TestCase):
    def test_seed_definitions_build_six_scenarios(self) -> None:
        events = main.TEST_EVENT_SEEDS
        self.assertEqual(len(events), 6)
        self.assertEqual(
            {event["event_id"] for event in events},
            {
                "normal-event",
                "traffic-spike-event",
                "db-bottleneck-event",
                "budget-exceeded-event",
                "policy-blocked-event",
                "missing-data-event",
            },
        )
        missing = next(
            event for event in events if event["event_id"] == "missing-data-event"
        )
        self.assertTrue(missing["omit_traffic_signal"])
        self.assertTrue(missing["omit_cost_signal"])

    def test_event_row_serialization(self) -> None:
        self.assertEqual(
            main.event_row_to_dict(("normal-event", "Normal", "A", 100000, "09:00 KST")),
            {
                "event_id": "normal-event",
                "title": "Normal",
                "grade": "A",
                "target_users": 100000,
                "scheduled_at": "09:00 KST",
            },
        )

    def test_running_and_completed_rows_are_merged(self) -> None:
        rows = [
            {
                "agent_name": "Traffic Forecast Agent",
                "agent_key": "traffic_forecast",
                "status": "running",
                "result": {"agent_key": "traffic_forecast"},
                "input_context": {"event": {"event_id": "normal-event"}},
                "started_at": "start",
                "created_at": "start",
            },
            {
                "agent_name": "Traffic Forecast Agent",
                "agent_key": "traffic_forecast",
                "status": "completed",
                "result": {"result": {"peak_rps_after": 348}},
                "confidence": 0.82,
                "reasoning_source": "rule+llm",
                "evidence": ["metric"],
                "warnings": [],
                "data_requests": [],
                "completed_at": "end",
                "created_at": "end",
            },
        ]
        merged = main.merge_agent_decision_rows(rows, AGENT_SEQUENCE)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["status"], "completed")
        self.assertEqual(merged[0]["confidence"], 0.82)
        self.assertEqual(merged[0]["reasoning_source"], "rule+llm")
        self.assertEqual(merged[0]["input_context"]["event"]["event_id"], "normal-event")
        self.assertEqual(merged[0]["result"]["peak_rps_after"], 348)

    def test_broker_log_is_normalized_and_cache_is_enriched(self) -> None:
        cache_key = 'traffic_forecast:reforecast:{"push_window_minutes":20}'
        entries = [
            {
                "target_agent": "traffic_forecast",
                "operation": "reforecast",
                "parameters": {"push_window_minutes": 20},
                "required_fields": ["peak_rps_after", "required_app_pods"],
                "call_stack": ["bottleneck_capacity"],
                "cache_key": cache_key,
                "cache_hit": False,
                "_broker_status": "completed",
            },
            {
                "target_agent": "traffic_forecast",
                "operation": "reforecast",
                "cache_key": cache_key,
                "cache_hit": True,
                "_broker_status": "completed",
            },
        ]
        payloads = [
            {
                "type": "broker_data_request",
                "target_agent": "traffic_forecast",
                "operation": "reforecast",
                "parameters": {"push_window_minutes": 20},
                "reason": "DB CPU high",
            }
        ]
        normalized = main.normalize_broker_call_log(entries, payloads)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["requester_agent"], "bottleneck_capacity")
        self.assertEqual(normalized[1]["reason"], "DB CPU high")
        self.assertTrue(normalized[1]["cache_hit"])
        self.assertEqual(
            normalized[1]["result_fields"],
            ["peak_rps_after", "required_app_pods"],
        )

    def test_retry_response_shape(self) -> None:
        self.assertEqual(
            main.retry_response("finops-new123"),
            {"new_workflow_id": "finops-new123"},
        )

    def test_supported_agent_statuses_match_ui_contract(self) -> None:
        ui_source = (MAS_ROOT / "pods" / "finops" / "ui" / "app" / "main.py").read_text(
            encoding="utf-8"
        )
        for status in [
            "completed",
            "needs_data",
            "blocked",
            "failed",
            "requires_review",
            "running",
        ]:
            self.assertIn(f"status-{status}", ui_source)


if __name__ == "__main__":
    unittest.main()
