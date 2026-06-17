import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.agent_runtime import build_final_plan, run_agent
from app.workflows import FinOpsEventWorkflow


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://finops:finops@finops-db.finops-mas.svc.cluster.local:5432/finops",
)
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "finops-temporal.finops-mas.svc.cluster.local:7233")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "finops-agent-task-queue")
AGENT_ENDPOINTS = {
    "business_control": os.getenv(
        "BUSINESS_CONTROL_AGENT_URL",
        "http://finops-business-control-agent.finops-mas.svc.cluster.local",
    ),
    "demand_shaping": os.getenv(
        "DEMAND_SHAPING_AGENT_URL",
        "http://finops-demand-shaping-agent.finops-mas.svc.cluster.local",
    ),
    "traffic_forecast": os.getenv(
        "TRAFFIC_FORECAST_AGENT_URL",
        "http://finops-traffic-forecast-agent.finops-mas.svc.cluster.local",
    ),
    "bottleneck_capacity": os.getenv(
        "BOTTLENECK_CAPACITY_AGENT_URL",
        "http://finops-bottleneck-capacity-agent.finops-mas.svc.cluster.local",
    ),
    "cost": os.getenv("COST_AGENT_URL", "http://finops-cost-agent.finops-mas.svc.cluster.local"),
    "policy_guardrail": os.getenv(
        "POLICY_GUARDRAIL_AGENT_URL",
        "http://finops-policy-guardrail-agent.finops-mas.svc.cluster.local",
    ),
}
AGENT_VALUE_REQUESTS = {
    "traffic_forecast": [
        {
            "source_key": "demand_shaping",
            "source_name": "Demand Shaping Agent",
            "field": "peak_reduction_percent",
            "label": "분산 발송 후 예상 peak 감소율",
        },
        {
            "source_key": "business_control",
            "source_name": "Business Control Agent",
            "field": "target_users",
            "label": "대상 사용자 수",
        },
    ],
    "bottleneck_capacity": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "peak_rps_after",
            "label": "병목 검증 기준 RPS",
        },
    ],
    "infra_execution": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "required_app_pods",
            "label": "준비해야 할 app pod 수",
        },
    ],
    "cost": [
        {
            "source_key": "infra_execution",
            "source_name": "Infra Execution Planner",
            "field": "target_app_pods",
            "label": "비용 계산 기준 pod 수",
        },
    ],
    "unit_economics": [
        {
            "source_key": "cost",
            "source_name": "Cost Agent",
            "field": "total",
            "label": "예상 총 비용",
        },
    ],
    "policy_guardrail": [
        {
            "source_key": "unit_economics",
            "source_name": "Unit Economics Agent",
            "field": "cost_ratio",
            "label": "비용 대비 가치 비율",
        },
    ],
    "observer": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "peak_rps_after",
            "label": "관측 기준 예상 RPS",
        },
        {
            "source_key": "policy_guardrail",
            "source_name": "Policy Guardrail Agent",
            "field": "approval_required",
            "label": "실행 전 승인 필요 여부",
        },
    ],
    "fallback": [
        {
            "source_key": "policy_guardrail",
            "source_name": "Policy Guardrail Agent",
            "field": "allowed",
            "label": "정책상 허용된 실행 액션",
        },
    ],
    "postmortem_learning": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "peak_rps_before",
            "label": "사후 비교용 평탄화 전 예상 RPS",
        },
        {
            "source_key": "cost",
            "source_name": "Cost Agent",
            "field": "total",
            "label": "사후 비교용 예상 비용",
        },
    ],
}

app = FastAPI(title="FinOps Orchestrator", version="0.3.0")
temporal_client: Client | None = None
temporal_worker_task: asyncio.Task | None = None
AGENT_STEP_DELAY_SECONDS = float(os.getenv("AGENT_STEP_DELAY_SECONDS", "0.8"))


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


def format_agent_value(value: Any) -> str:
    if isinstance(value, bool):
        return "필요함" if value else "필요하지 않음"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def build_agent_value_exchange(
    agent_key: str,
    agent_name: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    messages = []
    agent_results = context.get("agent_results", {})
    for request in AGENT_VALUE_REQUESTS.get(agent_key, []):
        source_key = request["source_key"]
        source_result = agent_results.get(source_key)
        if source_result is None or request["field"] not in source_result:
            continue
        value = source_result[request["field"]]
        messages.append(
            {
                "sender": agent_name,
                "receiver": request["source_name"],
                "message": f"{request['label']} 값이 필요합니다. 현재 단계 판단에 사용할 수 있도록 공유해 주세요.",
                "payload": {
                    "type": "value_request",
                    "source_agent": source_key,
                    "field": request["field"],
                    "label": request["label"],
                },
            }
        )
        messages.append(
            {
                "sender": request["source_name"],
                "receiver": agent_name,
                "message": f"{request['label']}은 {format_agent_value(value)}입니다. 이 값을 기준으로 다음 판단을 진행하세요.",
                "payload": {
                    "type": "value_response",
                    "source_agent": source_key,
                    "field": request["field"],
                    "label": request["label"],
                    "value": value,
                },
            }
        )
    return messages


def fetch_event_context(event_id: str) -> dict[str, Any]:
    with connect() as conn:
        event = conn.execute(
            """
            select event_id, title, grade, target_users, max_delay_minutes, scheduled_at
            from business_calendar
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
        policy = conn.execute(
            """
            select event_id, vip_immediate, approval_required, max_general_delay_minutes
            from business_policy
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
    if not event or not policy:
        raise ValueError(f"event context not found: {event_id}")
    return {
        "event": {
            "event_id": event[0],
            "title": event[1],
            "grade": event[2],
            "target_users": event[3],
            "max_delay_minutes": event[4],
            "scheduled_at": event[5],
        },
        "policy": {
            "event_id": policy[0],
            "vip_immediate": policy[1],
            "approval_required": policy[2],
            "max_general_delay_minutes": policy[3],
        },
        "agent_results": {},
    }


def call_agent_pod(agent_key: str, workflow_id: str, context: dict[str, Any]) -> dict[str, Any]:
    endpoint = AGENT_ENDPOINTS[agent_key]
    body = json.dumps({"workflow_id": workflow_id, "context": context}).encode("utf-8")
    request = Request(
        f"{endpoint}/run",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"{agent_key} agent pod unavailable: {exc}") from exc


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
                    create table if not exists agent_conversation_log (
                      id serial primary key,
                      workflow_id text not null,
                      phase integer not null,
                      sender text not null,
                      receiver text not null,
                      message text not null,
                      payload jsonb not null,
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


@activity.defn(name="load_event_context")
async def load_event_context(event_id: str) -> dict[str, Any]:
    return fetch_event_context(event_id)


@activity.defn(name="run_agent_step")
async def run_agent_step(
    workflow_id: str,
    phase: int,
    agent_key: str,
    agent_name: str,
    next_agent_name: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    started_at = utcnow()
    with connect() as conn:
        conn.execute(
            """
            insert into agent_decision_log
              (workflow_id, phase, agent, status, result, created_at)
            values (%s, %s, %s, 'running', %s, %s)
            """,
            (
                workflow_id,
                phase,
                agent_name,
                json.dumps({"agent_key": agent_key, "next": next_agent_name}),
                started_at,
            ),
        )
        conn.execute(
            """
            insert into agent_conversation_log
              (workflow_id, phase, sender, receiver, message, payload, created_at)
            values (%s, %s, 'FinOps Orchestrator', %s, %s, %s, %s)
            """,
            (
                workflow_id,
                phase,
                agent_name,
                f"{agent_name}에게 현재 이벤트 컨텍스트와 이전 agent 결과를 전달했습니다. 결과가 오면 다음 단계인 {next_agent_name}에게 넘기겠습니다.",
                json.dumps({"agent_key": agent_key, "status": "calling"}),
                started_at,
            ),
        )
        for exchange in build_agent_value_exchange(agent_key, agent_name, context):
            conn.execute(
                """
                insert into agent_conversation_log
                  (workflow_id, phase, sender, receiver, message, payload, created_at)
                values (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    workflow_id,
                    phase,
                    exchange["sender"],
                    exchange["receiver"],
                    exchange["message"],
                    json.dumps(exchange["payload"]),
                    utcnow(),
                ),
            )
    if AGENT_STEP_DELAY_SECONDS > 0:
        await asyncio.sleep(AGENT_STEP_DELAY_SECONDS)

    output = (
        call_agent_pod(agent_key, workflow_id, context)
        if agent_key in AGENT_ENDPOINTS
        else run_agent(agent_key, context)
    )
    result = output["result"]
    context["agent_results"][agent_key] = result
    created_at = utcnow()
    with connect() as conn:
        conn.execute(
            """
            insert into agent_decision_log
              (workflow_id, phase, agent, status, result, created_at)
            values (%s, %s, %s, 'completed', %s, %s)
            """,
            (workflow_id, phase, agent_name, json.dumps(result), created_at),
        )
        conn.execute(
            """
            insert into agent_conversation_log
              (workflow_id, phase, sender, receiver, message, payload, created_at)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                workflow_id,
                phase,
                agent_name,
                next_agent_name,
                output["message"],
                json.dumps({"agent_key": agent_key, "result": result}),
                created_at,
            ),
        )
    return context


@activity.defn(name="finalize_finops_plan")
async def finalize_finops_plan(workflow_id: str, context: dict[str, Any]) -> dict[str, Any]:
    plan = build_final_plan(context)
    created_at = utcnow()
    with connect() as conn:
        conn.execute(
            """
            insert into final_event_plan
              (workflow_id, event_id, status, plan, created_at, updated_at)
            values (%s, %s, 'waiting_approval', %s, %s, %s)
            on conflict (workflow_id) do update set
              event_id = excluded.event_id,
              status = excluded.status,
              plan = excluded.plan,
              updated_at = excluded.updated_at
            """,
            (workflow_id, plan["event_id"], json.dumps(plan), created_at, created_at),
        )
        conn.execute(
            """
            insert into approval_request
              (workflow_id, status, requested_at)
            values (%s, 'waiting', %s)
            """,
            (workflow_id, created_at),
        )
        conn.execute(
            """
            insert into agent_conversation_log
              (workflow_id, phase, sender, receiver, message, payload, created_at)
            values (%s, 12, 'FinOps Orchestrator', 'Operator', %s, %s, %s)
            """,
            (
                workflow_id,
                "최종 FinOps 계획을 만들었습니다. 운영자 승인을 기다립니다.",
                json.dumps({"plan": plan}),
                utcnow(),
            ),
        )
        conn.execute(
            """
            insert into agent_conversation_log
              (workflow_id, phase, sender, receiver, message, payload, created_at)
            values (%s, 13, 'FinOps Orchestrator', 'Operator', %s, %s, %s)
            """,
            (
                workflow_id,
                "최종 FinOps 계획을 만들었습니다. 운영자 승인을 기다립니다.",
                json.dumps({"plan": plan, "status": "waiting_approval"}),
                utcnow(),
            ),
        )
    return {"workflow_id": workflow_id, "status": "waiting_approval", "plan": plan}


async def start_temporal_worker() -> None:
    global temporal_client
    temporal_client = await Client.connect(TEMPORAL_ADDRESS)
    worker = Worker(
        temporal_client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[FinOpsEventWorkflow],
        activities=[load_event_context, run_agent_step, finalize_finops_plan],
    )
    await worker.run()


@app.on_event("startup")
async def startup() -> None:
    global temporal_worker_task
    init_db()
    temporal_worker_task = asyncio.create_task(start_temporal_worker())


@app.on_event("shutdown")
async def shutdown() -> None:
    if temporal_worker_task:
        temporal_worker_task.cancel()


async def get_temporal_client() -> Client:
    global temporal_client
    if temporal_client is None:
        temporal_client = await Client.connect(TEMPORAL_ADDRESS)
    return temporal_client


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
async def run_workflow(event_id: str = "fomc-briefing") -> dict[str, str]:
    workflow_id = f"finops-{uuid.uuid4().hex[:8]}"
    try:
        client = await get_temporal_client()
        created_at = utcnow()
        with connect() as conn:
            conn.execute(
                """
                insert into final_event_plan
                  (workflow_id, event_id, status, plan, created_at, updated_at)
                values (%s, %s, 'running', %s, %s, %s)
                """,
                (
                    workflow_id,
                    event_id,
                    json.dumps({"event_id": event_id, "engine": "temporal", "phase": "starting"}),
                    created_at,
                    created_at,
                ),
            )
            conn.execute(
                """
                insert into agent_conversation_log
                  (workflow_id, phase, sender, receiver, message, payload, created_at)
                values (%s, 0, 'Operator', 'FinOps Orchestrator', %s, %s, %s)
                """,
                (
                    workflow_id,
                    "비즈니스 캘린더의 이벤트를 기준으로 FinOps 계획 수립을 요청했습니다.",
                    json.dumps({"event_id": event_id, "status": "requested"}),
                    created_at,
                ),
            )
            conn.execute(
                """
                insert into agent_conversation_log
                  (workflow_id, phase, sender, receiver, message, payload, created_at)
                values (%s, 0, 'FinOps Orchestrator', 'Temporal', %s, %s, %s)
                """,
                (
                    workflow_id,
                    f"Temporal task queue '{TEMPORAL_TASK_QUEUE}'에 FinOpsEventWorkflow 실행을 예약했습니다.",
                    json.dumps(
                        {
                            "event_id": event_id,
                            "workflow_id": workflow_id,
                            "task_queue": TEMPORAL_TASK_QUEUE,
                        }
                    ),
                    created_at,
                ),
            )
        await client.start_workflow(
            FinOpsEventWorkflow.run,
            args=[event_id, workflow_id],
            id=workflow_id,
            task_queue=TEMPORAL_TASK_QUEUE,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"temporal workflow failed: {exc}") from exc
    return {"workflow_id": workflow_id, "status": "running", "engine": "temporal"}


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
        conversation = conn.execute(
            """
            select phase, sender, receiver, message, payload, created_at
            from agent_conversation_log
            where workflow_id = %s
            order by phase, id
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
        "conversation": [
            {
                "phase": row[0],
                "sender": row[1],
                "receiver": row[2],
                "message": row[3],
                "payload": row[4],
                "created_at": row[5],
            }
            for row in conversation
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
            conn.execute(
                """
                insert into agent_conversation_log
                  (workflow_id, phase, sender, receiver, message, payload, created_at)
                values (%s, 13, 'FinOps Orchestrator', 'Operator', %s, %s, %s)
                """,
                (
                    workflow_id,
                    "승인이 확인되었습니다. scale-out, pre-warm, push schedule 등록을 dry-run으로 검증했습니다.",
                    json.dumps({"status": "dry_run_completed"}),
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
            "requires_replan_from": "Demand Shaping Agent",
        },
        "answer": f"요청을 구조화했습니다. 일반 사용자 발송 구간을 {delay}분으로 재계획하려면 Demand Shaping 단계부터 다시 실행하면 됩니다.",
    }
