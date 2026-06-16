import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://finops:finops@finops-db.finops-mas.svc.cluster.local:5432/finops",
)

app = FastAPI(title="FinOps Orchestrator", version="0.1.0")


class ChatRequest(BaseModel):
    event_id: str = "fomc-briefing"
    message: str


class ApprovalRequest(BaseModel):
    approved_by: str = "operator"
    decision: str = "approved"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect():
    return psycopg.connect(DATABASE_URL, autocommit=True)


def init_db() -> None:
    for _ in range(20):
        try:
            with connect() as conn:
                conn.execute(
                    """
                    create table if not exists business_calendar (
                      event_id text primary key,
                      title text not null,
                      grade text not null,
                      target_users integer not null,
                      max_delay_minutes integer not null,
                      scheduled_at text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists business_policy (
                      event_id text primary key,
                      vip_immediate boolean not null,
                      approval_required boolean not null,
                      max_general_delay_minutes integer not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists agent_decision_log (
                      id serial primary key,
                      workflow_id text not null,
                      phase integer not null,
                      agent text not null,
                      status text not null,
                      result jsonb not null,
                      created_at text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists final_event_plan (
                      workflow_id text primary key,
                      event_id text not null,
                      status text not null,
                      plan jsonb not null,
                      created_at text not null,
                      updated_at text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists approval_request (
                      workflow_id text primary key,
                      status text not null,
                      requested_at text not null,
                      decided_at text,
                      decided_by text
                    )
                    """
                )
                seed(conn)
            return
        except psycopg.OperationalError:
            time.sleep(2)
    raise RuntimeError("database is not reachable")


def seed(conn) -> None:
    conn.execute(
        """
        insert into business_calendar
          (event_id, title, grade, target_users, max_delay_minutes, scheduled_at)
        values
          ('fomc-briefing', 'FOMC stock briefing push', 'S', 350000, 10, '08:30 KST')
        on conflict (event_id) do nothing
        """
    )
    conn.execute(
        """
        insert into business_policy
          (event_id, vip_immediate, approval_required, max_general_delay_minutes)
        values
          ('fomc-briefing', true, true, 10)
        on conflict (event_id) do nothing
        """
    )


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/calendar")
def calendar() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "select event_id, title, grade, target_users, max_delay_minutes, scheduled_at from business_calendar"
        ).fetchall()
    return [
        {
            "event_id": row[0],
            "title": row[1],
            "grade": row[2],
            "target_users": row[3],
            "max_delay_minutes": row[4],
            "scheduled_at": row[5],
        }
        for row in rows
    ]


@app.post("/api/workflows/run")
def run_workflow(event_id: str = "fomc-briefing") -> dict[str, str]:
    workflow_id = f"finops-{uuid.uuid4().hex[:8]}"
    phases = build_phases(event_id)
    with connect() as conn:
        for phase in phases:
            conn.execute(
                """
                insert into agent_decision_log
                  (workflow_id, phase, agent, status, result, created_at)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    workflow_id,
                    phase["phase"],
                    phase["agent"],
                    phase["status"],
                    json.dumps(phase["result"]),
                    utcnow(),
                ),
            )
        plan = {
            "event_id": event_id,
            "peak_rps_before": 1420,
            "peak_rps_after": 820,
            "required_app_pods": 29,
            "estimated_cost_usd": 50.3,
            "approval_required": True,
            "execution_mode": "dry_run",
            "recommended_actions": [
                "Send VIP users immediately",
                "Spread general users across 10 minutes",
                "Pre-warm CDN and cache 15 minutes before push",
                "Scale app pods to 29, then scale down after observed RPS drops",
            ],
        }
        conn.execute(
            """
            insert into final_event_plan
              (workflow_id, event_id, status, plan, created_at, updated_at)
            values (%s, %s, 'waiting_approval', %s, %s, %s)
            """,
            (workflow_id, event_id, json.dumps(plan), utcnow(), utcnow()),
        )
        conn.execute(
            """
            insert into approval_request
              (workflow_id, status, requested_at)
            values (%s, 'waiting', %s)
            """,
            (workflow_id, utcnow()),
        )
    return {"workflow_id": workflow_id, "status": "waiting_approval"}


@app.get("/api/workflows")
def workflows() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            select workflow_id, event_id, status, plan, updated_at
            from final_event_plan
            order by updated_at desc
            limit 10
            """
        ).fetchall()
    return [
        {
            "workflow_id": row[0],
            "event_id": row[1],
            "status": row[2],
            "plan": row[3],
            "updated_at": row[4],
        }
        for row in rows
    ]


@app.get("/api/workflows/{workflow_id}")
def workflow_detail(workflow_id: str) -> dict[str, Any]:
    with connect() as conn:
        plan = conn.execute(
            "select workflow_id, event_id, status, plan, updated_at from final_event_plan where workflow_id = %s",
            (workflow_id,),
        ).fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="workflow not found")
        logs = conn.execute(
            """
            select phase, agent, status, result, created_at
            from agent_decision_log
            where workflow_id = %s
            order by phase
            """,
            (workflow_id,),
        ).fetchall()
    return {
        "workflow_id": plan[0],
        "event_id": plan[1],
        "status": plan[2],
        "plan": plan[3],
        "updated_at": plan[4],
        "timeline": [
            {
                "phase": row[0],
                "agent": row[1],
                "status": row[2],
                "result": row[3],
                "created_at": row[4],
            }
            for row in logs
        ],
    }


@app.post("/api/workflows/{workflow_id}/approve")
def approve(workflow_id: str, request: ApprovalRequest) -> dict[str, str]:
    status = "approved" if request.decision == "approved" else "rejected"
    with connect() as conn:
        existing = conn.execute(
            "select workflow_id from final_event_plan where workflow_id = %s",
            (workflow_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="workflow not found")
        conn.execute(
            """
            update approval_request
            set status = %s, decided_at = %s, decided_by = %s
            where workflow_id = %s
            """,
            (status, utcnow(), request.approved_by, workflow_id),
        )
        final_status = "dry_run_completed" if status == "approved" else "rejected"
        conn.execute(
            """
            update final_event_plan
            set status = %s, updated_at = %s
            where workflow_id = %s
            """,
            (final_status, utcnow(), workflow_id),
        )
        if status == "approved":
            conn.execute(
                """
                insert into agent_decision_log
                  (workflow_id, phase, agent, status, result, created_at)
                values (%s, 13, 'Dry-run Execution', 'completed', %s, %s)
                """,
                (
                    workflow_id,
                    json.dumps(
                        {
                            "scale_app_pods": "dry_run_success",
                            "cdn_prewarm": "dry_run_success",
                            "push_schedule": "dry_run_success",
                        }
                    ),
                    utcnow(),
                ),
            )
    return {"workflow_id": workflow_id, "status": final_status}


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    message = request.message.strip()
    delay = 20 if "20" in message else 10
    return {
        "event_id": request.event_id,
        "agent": "Business Control Agent",
        "change_request": {
            "max_delivery_delay_minutes": delay,
            "push_window_minutes": delay,
            "requires_replan_from": "Phase 2",
        },
        "answer": f"General-user push window can be replanned to {delay} minutes after policy validation.",
    }


def build_phases(event_id: str) -> list[dict[str, Any]]:
    return [
        phase(1, "Business Control Agent", {"event_id": event_id, "grade": "S", "approval_required": True}),
        phase(2, "Demand Shaping Agent", {"vip": "immediate", "general_users": "spread_over_10m", "peak_reduction": "42%"}),
        phase(3, "Traffic Forecast Agent", {"peak_rps_before": 1420, "peak_rps_after": 820, "required_app_pods": 29}),
        phase(4, "Bottleneck Capacity Agent", {"db_cpu": "68%", "cache_hit_ratio": "91%", "status": "warning"}),
        phase(5, "Infra Execution Planner", {"scale_out_at": "T-20m", "prewarm_at": "T-15m", "scale_down": "observed_rps_based"}),
        phase(6, "Cost Agent", {"eks": 31.2, "network": 8.1, "logs": 3.4, "push": 7.6, "total": 50.3}),
        phase(7, "Unit Economics Agent", {"expected_value_usd": 4200, "cost_ratio": "1.2%", "override": False}),
        phase(8, "Policy Guardrail Agent", {"allowed": ["scale_out", "prewarm", "spread_push"], "approval_required": True}),
        phase(9, "Final Plan", {"status": "waiting_approval"}),
        phase(10, "Observer Agent", {"mode": "armed", "recommendation": "scale_down_if_actual_rps_below_600"}),
        phase(11, "Fallback Planner", {"vip_only": True, "general_hold": True, "static_report": True}),
        phase(12, "Postmortem Learning Agent", {"profile_update": "pending_after_execution"}),
    ]


def phase(number: int, agent: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"phase": number, "agent": agent, "status": "completed", "result": result}
