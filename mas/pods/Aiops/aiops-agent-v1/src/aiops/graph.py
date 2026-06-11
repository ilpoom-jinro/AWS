"""
graph.py — LangGraph 상태 머신 조립

[v0.2 수정사항]
- 기존: detect/wait_approval/verify/rollback에서 "monitor"로 복귀하는 내부 루프 구조
  → LangGraph recursion_limit(기본 25)에 걸려 GraphRecursionError로 크래시
- 수정: 한 사이클(1회 스캔~조치)이 끝나면 END로 종료.
  주기적 재실행은 main.py의 외부 루프(asyncio sleep)가 담당한다.

흐름 요약 (1 사이클):
  monitor → detect
  detect  → [이벤트 있음] analyze  / [없음] END (다음 주기에 재스캔)
  analyze → plan
  plan    → wait_approval
  wait_approval → [승인] execute  / [거부·타임아웃·조사권고] END
  execute → verify
  verify  → [정상] END  / [재이상] rollback
  rollback → END
"""
from __future__ import annotations

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
    return "analyze" if state.get("events") else END


def _route_approval(state: AgentState) -> str:
    """승인 여부에 따라 다음 노드 결정"""
    return "execute" if state.get("approved_plan") else END


def _route_verify(state: AgentState) -> str:
    """검증 결과에 따라 다음 노드 결정"""
    return END if state.get("verify_ok") else "rollback"


def build_graph():
    """컴파일된 LangGraph 그래프 반환 (1 사이클 = 1 invoke)"""
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
    g.add_edge("monitor", "detect")

    # 조건 분기 (END 종료 → 외부 루프가 다음 주기 재실행)
    g.add_conditional_edges("detect",        _route_detect)
    g.add_conditional_edges("wait_approval", _route_approval)
    g.add_conditional_edges("verify",        _route_verify)

    # 단순 엣지
    g.add_edge("analyze",  "plan")
    g.add_edge("plan",     "wait_approval")
    g.add_edge("execute",  "verify")
    g.add_edge("rollback", END)

    # 체크포인터 제거: 사이클 단위 실행이라 불필요.
    # (interrupt 기반 HITL로 확장할 때 checkpointer 재도입)
    return g.compile()
