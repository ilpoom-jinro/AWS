from __future__ import annotations

import json
from typing import Any


TEST_EVENT_SEEDS = [
    {"event_id": "normal-event", "title": "일반 비즈니스 푸시", "grade": "A", "target_users": 100000, "scheduled_at": "09:00", "baseline_peak_rps": 600, "required_app_pods": 12, "rds_cpu_percent": 45, "event_incremental_budget_usd": 60.0},
    {"event_id": "traffic-spike-event", "title": "대규모 트래픽 급증 푸시", "grade": "S", "target_users": 500000, "scheduled_at": "10:00", "baseline_peak_rps": 3500, "required_app_pods": 65, "rds_cpu_percent": 72, "event_incremental_budget_usd": 200.0},
    {"event_id": "db-bottleneck-event", "title": "DB 병목 대응 리허설", "grade": "A", "target_users": 200000, "scheduled_at": "11:00", "baseline_peak_rps": 1100, "traffic_rps": 2000, "required_app_pods": 36, "rds_cpu_percent": 88, "event_incremental_budget_usd": 120.0},
    {"event_id": "budget-exceeded-event", "title": "저예산 제한 푸시", "grade": "B", "target_users": 50000, "scheduled_at": "12:00", "baseline_peak_rps": 500, "required_app_pods": 10, "rds_cpu_percent": 42, "event_incremental_budget_usd": 20.0},
    {"event_id": "policy-blocked-event", "title": "정책 차단 검증 푸시", "grade": "S", "target_users": 350000, "scheduled_at": "13:00", "baseline_peak_rps": 1420, "required_app_pods": 29, "rds_cpu_percent": 68, "event_incremental_budget_usd": 95.0, "allowed_actions": False},
    {"event_id": "missing-data-event", "title": "관측 데이터 누락 푸시", "grade": "A", "target_users": 150000, "scheduled_at": "14:00", "baseline_peak_rps": 900, "required_app_pods": 18, "rds_cpu_percent": 55, "event_incremental_budget_usd": 75.0, "omit_traffic_signal": True, "omit_cost_signal": True},
    {"event_id": "soft-bottleneck-event", "title": "경계성 병목 판단 테스트", "grade": "A", "target_users": 180000, "scheduled_at": "14:00", "baseline_peak_rps": 950, "required_app_pods": 22, "rds_cpu_percent": 75, "redis_cache_hit_ratio_percent": 72, "event_incremental_budget_usd": 95.0},
    {
    "event_id": "vip-small-briefing",
    "title": "VIP 소규모 리서치 알림 푸시",
    "grade": "B",
    "target_users": 600,
    "scheduled_at": "09:10",
    "baseline_peak_rps": 20,
    "traffic_rps": 4,
    "required_app_pods": 1,
    "rds_cpu_percent": 12,
    "redis_cache_hit_ratio_percent": 98,
    "event_incremental_budget_usd": 51.0,
},
]


def event_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {"event_id": row[0], "title": row[1], "grade": row[2], "target_users": row[3], "scheduled_at": row[4]}


def merge_agent_decision_rows(rows: list[dict[str, Any]], agent_sequence: list[tuple[str, str]]) -> list[dict[str, Any]]:
    agent_order = {key: index for index, (key, _) in enumerate(agent_sequence)}
    agent_key_by_name = {name: key for key, name in agent_sequence}
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        agent_key = row.get("agent_key") or agent_key_by_name.get(row["agent_name"])
        if not agent_key or agent_key not in agent_order:
            continue
        item = merged.setdefault(agent_key, {"agent_key": agent_key, "agent_name": row["agent_name"], "status": "pending", "confidence": None, "reasoning_source": None, "result": {}, "evidence": [], "warnings": [], "data_requests": [], "input_context": {}, "started_at": None, "completed_at": None})
        payload = row.get("result") if isinstance(row.get("result"), dict) else {}
        if row["status"] == "running":
            item.update(status="running", input_context=row.get("input_context") or {}, started_at=row.get("started_at") or row.get("created_at"))
            continue
        item.update(status=row["status"], confidence=float(row["confidence"]) if row.get("confidence") is not None else payload.get("confidence"), reasoning_source=row.get("reasoning_source") or payload.get("reasoning_source"), result=payload.get("result", payload), evidence=row.get("evidence") or payload.get("evidence", []), warnings=row.get("warnings") or payload.get("warnings", []), data_requests=row.get("data_requests") or payload.get("data_requests", []), completed_at=row.get("completed_at") or row.get("created_at"))
    return sorted(merged.values(), key=lambda item: agent_order[item["agent_key"]])


def normalize_broker_call_log(entries: list[dict[str, Any]], request_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_by_cache_key = {entry.get("cache_key"): entry for entry in entries if entry.get("cache_key") and not entry.get("cache_hit")}
    reasons = {}
    for payload in request_payloads:
        if payload.get("type") == "broker_data_request":
            key = json.dumps(payload.get("parameters", {}), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            reasons[(payload.get("target_agent", ""), payload.get("operation", ""), key)] = payload.get("reason", "")
    normalized = []
    for entry in entries:
        source = source_by_cache_key.get(entry.get("cache_key"), entry)
        parameters = entry.get("parameters", source.get("parameters", {}))
        parameters_key = json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        target_agent = entry.get("target_agent", source.get("target_agent"))
        operation = entry.get("operation", source.get("operation"))
        required_fields = entry.get("required_fields", source.get("required_fields", []))
        call_stack = entry.get("call_stack", source.get("call_stack", []))
        broker_status = entry.get("_broker_status", source.get("_broker_status"))
        normalized.append({"requester_agent": call_stack[-1] if call_stack else None, "target_agent": target_agent, "operation": operation, "parameters": parameters, "required_fields": required_fields, "reason": reasons.get((target_agent or "", operation or "", parameters_key), ""), "cache_hit": bool(entry.get("cache_hit", False)), "broker_status": broker_status or "failed", "result_fields": required_fields if broker_status == "completed" else []})
    return normalized


def retry_response(new_workflow_id: str) -> dict[str, str]:
    return {"new_workflow_id": new_workflow_id}
