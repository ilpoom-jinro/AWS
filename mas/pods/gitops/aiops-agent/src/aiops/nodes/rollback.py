"""
nodes/rollback.py — ROLLBACK 노드
VERIFY에서 이상이 재감지됐을 때 자동으로 롤백을 수행한다.

Helm release가 있으면 helm rollback, 없으면 kubectl rollout undo.
롤백 완료 후 Slack에 결과 + 수동 조사 권고를 알린다.
"""
from __future__ import annotations

import logging

from ..config import settings
from ..state import AgentState
from ..tools.k8s_client import _run_cmd
from ..tools.slack import SlackClient

logger = logging.getLogger(__name__)
_slack = SlackClient(settings.SLACK_BOT_TOKEN)


async def run(state: AgentState) -> AgentState:
    """ROLLBACK 노드 진입점"""
    plan = state.get("approved_plan")
    events = state.get("events", [])

    if not events:
        logger.warning("이벤트 없음 — 롤백 스킵")
        return {**state, "rollback_done": False}

    event = events[0]
    ns, pod_name = event["pod"].split("/", 1)
    context = settings.OPS_KUBE_CONTEXT if event["vpc"] == "vpc2" else settings.SERVICE_KUBE_CONTEXT

    # 대상 리소스 결정
    if plan and "helm/" in plan.get("target", ""):
        # Helm 롤백
        release = plan["target"].split("/")[-1]
        cmd = [
            "helm", "--kube-context", context,
            "rollback", release, "--wait",
            "--namespace", ns,
        ]
        rollback_type = f"Helm release `{release}`"
    else:
        # kubectl rollout undo — 파드 이름에서 Deployment 추출
        from .planner import _extract_deploy_name
        deploy = _extract_deploy_name(pod_name)
        cmd = [
            "kubectl", "--context", context,
            "rollout", "undo", f"deployment/{deploy}",
            "-n", ns,
        ]
        rollback_type = f"deployment/{deploy}"

    await _slack.post_message(
        settings.SLACK_CHANNEL,
        f"🔄 *자동 롤백 시작*\n대상: `{rollback_type}` (namespace: `{ns}`)",
    )

    returncode, output = await _run_cmd(cmd, timeout=300)
    ok = returncode == 0
    status_emoji = "✅" if ok else "❌"

    await _slack.post_message(
        settings.SLACK_CHANNEL,
        (
            f"{status_emoji} 롤백 {'완료' if ok else '실패'} (exitcode={returncode})\n"
            f"```{output[:600]}```\n\n"
            f"⚠️ *수동 조사가 필요합니다.* 담당 엔지니어를 확인해 주세요."
        ),
    )

    if not ok:
        logger.error("롤백 실패 (exitcode=%d): %s", returncode, output[:200])

    return {**state, "rollback_done": True}
