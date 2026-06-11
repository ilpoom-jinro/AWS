"""
nodes/executor.py — EXECUTE 노드

[v0.2 수정사항]
- Slack 클라이언트 lazy 초기화 (get_slack)
"""
from __future__ import annotations

import logging

from ..config import settings
from ..state import AgentState
from ..tools.k8s_client import _run_cmd
from ..tools.slack import get_slack

logger = logging.getLogger(__name__)


async def run(state: AgentState) -> AgentState:
    """EXECUTE 노드 진입점"""
    slack = get_slack()
    plan = state["approved_plan"]

    if not plan or not plan.get("command"):
        logger.warning("실행할 명령어 없음 — 스킵")
        return {**state, "exec_result": "명령어 없음"}

    cmd_str = " ".join(plan["command"])
    await slack.post_message(
        settings.SLACK_CHANNEL,
        f"🔧 *복구 실행 시작*\n전략: `{plan['strategy'].upper()}`\n명령어: `{cmd_str}`",
    )

    returncode, output = await _run_cmd(plan["command"], timeout=300)
    ok = returncode == 0
    status_emoji = "✅" if ok else "❌"

    await slack.post_message(
        settings.SLACK_CHANNEL,
        (
            f"{status_emoji} 복구 명령 완료 (exitcode={returncode})\n"
            f"```{output[:800]}```"
        ),
    )

    if not ok:
        logger.error("복구 명령 실패 (exitcode=%d): %s", returncode, output[:200])

    return {**state, "exec_result": output}
