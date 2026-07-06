from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MAS_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_APP = MAS_ROOT / "pods" / "finops" / "orchestrator" / "app"
if str(MAS_ROOT) not in sys.path:
    sys.path.insert(0, str(MAS_ROOT))
sys.path.insert(0, str(ORCHESTRATOR_APP))
sys.path.insert(0, str(MAS_ROOT / "pods" / "finops" / "orchestrator"))

import chat_tools  # noqa: E402
import chat_runtime  # noqa: E402

for path in (str(ORCHESTRATOR_APP), str(MAS_ROOT / "pods" / "finops" / "orchestrator")):
    if path in sys.path:
        sys.path.remove(path)
sys.modules.pop("app", None)
sys.modules.pop("app.chat_tools", None)


class ChatToolTests(unittest.TestCase):
    def test_agent_result_normalization_removes_input_context(self) -> None:
        row = (
            {
                "result": {"required_app_pods": 22},
                "input_context": {"secret": "large"},
                "evidence": ["forecast"],
            },
            ["column evidence"],
            ["warn"],
            0.82,
            "rule",
        )
        normalized = chat_tools.normalize_agent_result_row(row)
        self.assertEqual(
            set(normalized.keys()),
            {"result", "evidence", "warnings", "confidence", "reasoning_source"},
        )
        self.assertNotIn("input_context", normalized)
        self.assertEqual(normalized["result"], {"required_app_pods": 22})

    def test_tool_call_limit_stops_after_five(self) -> None:
        self.assertTrue(chat_runtime.should_continue_tool_loop(4))
        self.assertFalse(chat_runtime.should_continue_tool_loop(5))
        self.assertEqual(chat_runtime.CHAT_MAX_TOOL_CALLS, 5)

    def test_get_all_agent_results_returns_evidence(self) -> None:
        class FakeCursor:
            def fetchall(self):
                return [
                    (
                        "traffic_forecast",
                        "Traffic Forecast Agent",
                        {"result": {"required_app_pods": 29}},
                        ["기준 peak RPS는 1420입니다."],
                        [],
                        0.82,
                        "rule",
                        3,
                        101,
                    ),
                    (
                        "cost",
                        "Cost Agent",
                        {"result": {"total": 50.3}},
                        ["총 비용 계산식은 31.2 + 8.1 + 3.4 + 7.6 = $50.3입니다."],
                        [],
                        0.8,
                        "rule",
                        6,
                        102,
                    ),
                ]

        class FakeConn:
            def execute(self, query, params):
                return FakeCursor()

        results = chat_tools.get_all_agent_results(FakeConn(), "wf-test")

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["agent_key"], "traffic_forecast")
        self.assertEqual(results[0]["result"], {"required_app_pods": 29})
        self.assertEqual(
            results[0]["evidence"],
            ["기준 peak RPS는 1420입니다."],
        )

        self.assertEqual(results[1]["agent_key"], "cost")
        self.assertEqual(results[1]["result"], {"total": 50.3})
        self.assertEqual(
            results[1]["evidence"],
            ["총 비용 계산식은 31.2 + 8.1 + 3.4 + 7.6 = $50.3입니다."],
        )

    def test_get_all_agent_results_queries_latest_agent_rows(self) -> None:
        captured = {}

        class FakeCursor:
            def fetchall(self):
                return []

        class FakeConn:
            def execute(self, query, params):
                captured["query"] = query
                captured["params"] = params
                return FakeCursor()

        chat_tools.get_all_agent_results(FakeConn(), "wf-test")

        self.assertEqual(captured["params"], ("wf-test",))
        self.assertIn("distinct on (agent_key)", captured["query"])
        self.assertIn("order by agent_key, id desc", captured["query"])

    def test_get_all_agent_results_tool_is_registered(self) -> None:
        self.assertIn("get_all_agent_results", chat_runtime.TOOL_FUNCTIONS)

        tool_names = [
            tool["toolSpec"]["name"]
            for tool in chat_runtime.CHAT_TOOLS
        ]
        self.assertIn("get_all_agent_results", tool_names)

    def test_conversation_history_structure_is_preserved(self) -> None:
        history = chat_runtime.normalize_conversation_history(
            [
                {"role": "user", "content": "왜 22개야?"},
                {"role": "assistant", "content": "Traffic Forecast 기준입니다."},
                {"role": "tool", "content": {"ignored": True}},
            ]
        )
        self.assertEqual(
            history,
            [
                {"role": "user", "content": "왜 22개야?"},
                {"role": "assistant", "content": "Traffic Forecast 기준입니다."},
            ],
        )

    def test_llm_failure_returns_fallback_shape(self) -> None:
        async def run() -> dict:
            with patch.dict("sys.modules", {"shared.bedrock": None}):
                return await chat_runtime.run_report_chat(
                    conn=object(),
                    workflow_id="finops-test",
                    message="왜 Pod가 22개 필요한가?",
                    conversation_history=[],
                )

        response = asyncio.run(run())
        self.assertIn("보고서 데이터를 불러올 수 없습니다", response["answer"])
        self.assertEqual(response["sources"], [])
        self.assertEqual(response["tools_used"], [])
        self.assertEqual(response["conversation_history"][0]["role"], "user")

    def test_sources_extracted_from_agent_result_tool(self) -> None:
        sources: list[str] = []
        chat_runtime.append_unique(sources, "traffic_forecast")
        chat_runtime.append_unique(sources, "traffic_forecast")
        self.assertEqual(sources, ["traffic_forecast"])

    def test_tools_used_are_deduplicated(self) -> None:
        tools_used: list[str] = []
        chat_runtime.append_unique(tools_used, "get_agent_result")
        chat_runtime.append_unique(tools_used, "get_recommended_candidate")
        chat_runtime.append_unique(tools_used, "get_agent_result")
        self.assertEqual(tools_used, ["get_agent_result", "get_recommended_candidate"])


if __name__ == "__main__":
    unittest.main()
