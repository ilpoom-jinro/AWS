from __future__ import annotations

from typing import Any


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    return value


def _plan_row(conn, workflow_id: str) -> dict[str, Any]:
    row = conn.execute(
        "select plan from final_event_plan where workflow_id = %s",
        (workflow_id,),
    ).fetchone()
    if not row or not isinstance(row[0], dict):
        return {}
    return row[0]


def normalize_agent_result_row(row: Any) -> dict[str, Any]:
    if not row:
        return {}
    raw_result = row[0] if isinstance(row[0], dict) else {}
    embedded = raw_result.get("result") if isinstance(raw_result.get("result"), dict) else raw_result
    evidence = _json_value(row[1], raw_result.get("evidence", []))
    warnings = _json_value(row[2], raw_result.get("warnings", []))
    return {
        "result": embedded or {},
        "evidence": evidence or [],
        "warnings": warnings or [],
        "confidence": row[3] if row[3] is not None else raw_result.get("confidence"),
        "reasoning_source": row[4] or raw_result.get("reasoning_source"),
    }


def get_final_report(conn, workflow_id: str) -> dict:
    return _plan_row(conn, workflow_id)


def get_agent_result(conn, workflow_id: str, agent_key: str) -> dict:
    row = conn.execute(
        """
        select result, evidence, warnings, confidence, reasoning_source
        from agent_decision_log
        where workflow_id = %s
          and agent_key = %s
          and status <> 'running'
        order by id desc
        limit 1
        """,
        (workflow_id, agent_key),
    ).fetchone()
    return normalize_agent_result_row(row)


def get_all_agent_results(conn, workflow_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select agent_key, agent, result, evidence, warnings, confidence, reasoning_source
        from agent_decision_log
        where workflow_id = %s
          and status <> 'running'
          and agent_key is not null
        order by phase, id
        """,
        (workflow_id,),
    ).fetchall()

    results = []
    seen = set()

    for row in rows:
        agent_key = row[0]
        if not agent_key or agent_key in seen:
            continue
        seen.add(agent_key)

        normalized = normalize_agent_result_row(
            (row[2], row[3], row[4], row[5], row[6])
        )

        results.append(
            {
                "agent_key": agent_key,
                "agent_name": row[1],
                **normalized,
            }
        )

    return results


def get_plan_candidates(conn, workflow_id: str) -> list:
    plan = _plan_row(conn, workflow_id)
    candidates = plan.get("plan_candidates", [])
    return candidates if isinstance(candidates, list) else []


def get_recommended_candidate(conn, workflow_id: str) -> dict:
    plan = _plan_row(conn, workflow_id)
    candidate = plan.get("recommended_candidate")
    if not isinstance(candidate, dict):
        return {}
    return {
        "recommended_candidate": candidate,
        "recommendation_reason": plan.get("recommendation_reason", ""),
    }


def get_quality_gate_result(conn, workflow_id: str) -> dict:
    plan = _plan_row(conn, workflow_id)
    gate = plan.get("quality_gate_result", {})
    return gate if isinstance(gate, dict) else {}


def get_broker_log(conn, workflow_id: str) -> list:
    plan = _plan_row(conn, workflow_id)
    broker_log = plan.get("broker_call_log", [])
    return broker_log if isinstance(broker_log, list) else []


def get_data_collection_issues(conn, workflow_id: str) -> list:
    plan = _plan_row(conn, workflow_id)
    issues = plan.get("data_collection_issues", [])
    return issues if isinstance(issues, list) else []
