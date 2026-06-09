"""
graph.py — LangGraph 상태 머신 조립
모든 노드와 엣지를 한 곳에서 조립한다.
흐름 변경이 필요할 때 이 파일만 수정하면 된다.

흐름 요약:
  monitor → detect
  detect  → [이벤트 있으면] analyze  / [없으면] monitor
  analyze → plan
  plan    → wait_approval
  wait_approval → [승인] execute  / [거부/타임아웃] monitor
  execute → verify
  verify  → [정상] monitor  / [재이상] rollback
  rollback → monitor
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from .nodes import (
    analyzer,
    approver,
    detector,
    executor,
    monitor,
    planner,
    rollback,
    verifier,
)
from .state import AgentState


def _route_detect(state: AgentState) -> str:
    """이벤트 존재 여부에 따라 다음 노드 결정"""
    return "analyze" if state.get("events") else "monitor"


def _route_approval(state: AgentState) -> str:
    """승인 여부에 따라 다음 노드 결정"""
    return "execute" if state.get("approved_plan") else "monitor"


def _route_verify(state: AgentState) -> str:
    """검증 결과에 따라 다음 노드 결정"""
    return "monitor" if state.get("verify_ok") else "rollback"


def build_graph() -> StateGraph:
    """컴파일된 LangGraph StateGraph 반환"""
    g = StateGraph(AgentState)

    # ── 노드 등록 ────────────────────────────────────────────────
    g.add_node("monitor",       monitor.run)
    g.add_node("detect",        detector.run)
    g.add_node("analyze",       analyzer.run)
    g.add_node("plan",          planner.run)
    g.add_node("wait_approval", approver.run)
    g.add_node("execute",       executor.run)
    g.add_node("verify",        verifier.run)
    g.add_node("rollback",      rollback.run)

    # ── 엣지 ────────────────────────────────────────────────────
    g.set_entry_point("monitor")
    g.add_edge("monitor",  "detect")

    # 조건 분기
    g.add_conditional_edges("detect",        _route_detect)
    g.add_conditional_edges("wait_approval", _route_approval)
    g.add_conditional_edges("verify",        _route_verify)

    # 단순 엣지
    g.add_edge("analyze",  "plan")
    g.add_edge("plan",     "wait_approval")
    g.add_edge("execute",  "verify")
    g.add_edge("rollback", "monitor")

    # MemorySaver: 노드 간 상태 체크포인팅 (재시작 시 복원)
    return g.compile(checkpointer=MemorySaver())
