"""
main.py — FastAPI 진입점
1. LangGraph 에이전트 루프를 백그라운드 태스크로 실행
2. Slack WebHook(/slack/actions) 엔드포인트 제공
3. 수동 트리거 / RCA 조회 REST API 제공 (Bedrock Agent Action Group용)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .config import settings
from .graph import build_graph
from .nodes.approver import resolve_approval
from .state import initial_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── 글로벌 상태 ────────────────────────────────────────────────────
_graph = build_graph()
_thread_id = "main"
_latest_state: dict = {}


# ── LangGraph 실행 루프 ───────────────────────────────────────────

async def _agent_loop() -> None:
    """30초마다 monitor → detect → ... 사이클 실행"""
    global _latest_state
    state = initial_state()
    config = {"configurable": {"thread_id": _thread_id}}

    while True:
        try:
            # LangGraph invoke: monitor 진입 → detect에서 이벤트 없으면 자동 복귀
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _graph.invoke(state, config=config),
            )
            _latest_state = result
            state = result  # 다음 주기에 이전 상태 유지
        except Exception as exc:
            logger.exception("에이전트 루프 오류: %s", exc)

        await asyncio.sleep(settings.SCAN_INTERVAL_SEC)


# ── FastAPI 앱 ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 기동 시 Secrets 로드 + 에이전트 루프 시작
    settings.load_secrets()
    loop_task = asyncio.create_task(_agent_loop())
    logger.info(
        "AIOps Agent 시작 (interval=%ds, model=%s)",
        settings.SCAN_INTERVAL_SEC,
        settings.BEDROCK_MODEL_ID,
    )
    yield
    loop_task.cancel()


app = FastAPI(title="AIOps Bedrock Agent", lifespan=lifespan)


# ── Slack WebHook ─────────────────────────────────────────────────

@app.post("/slack/actions")
async def slack_actions(request: Request) -> Response:
    """
    Slack Block Kit 버튼 클릭 시 호출되는 WebHook.
    승인/거부 결과를 approver.resolve_approval()로 전달한다.
    """
    form = await request.form()
    raw_payload = form.get("payload", "{}")
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "invalid payload"}, status_code=400)

    actions = payload.get("actions", [])
    if not actions:
        return JSONResponse({"ok": True})

    action = actions[0]
    cb_id = payload.get("container", {}).get("block_id") or action.get("block_id", "")
    approved = action.get("value") == "approve"

    resolved = resolve_approval(cb_id, approved)
    logger.info(
        "Slack 액션 수신: cb_id=%s, approved=%s, resolved=%s",
        cb_id, approved, resolved,
    )
    return JSONResponse({"ok": True})


# ── REST API (Bedrock Agent Action Group용) ───────────────────────

@app.post("/trigger-scan")
async def trigger_scan(request: Request) -> JSONResponse:
    """즉시 스캔 트리거 — Bedrock Agent Action Group에서 호출"""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    logger.info("수동 스캔 트리거: vpc_filter=%s", body.get("vpc_filter", "all"))
    return JSONResponse({"ok": True, "message": "스캔이 다음 주기에 실행됩니다."})


@app.get("/get-latest-rca")
async def get_latest_rca() -> JSONResponse:
    """가장 최근 RCA 리포트 반환 — Bedrock Agent Action Group에서 호출"""
    return JSONResponse({
        "rca_report": _latest_state.get("rca_report", ""),
        "root_cause": _latest_state.get("rca_root_cause", "분석 결과 없음"),
        "events_count": len(_latest_state.get("events", [])),
        "timestamp": str(time.time()),
    })


@app.post("/approve-plan")
async def approve_plan(request: Request) -> JSONResponse:
    """API를 통한 복구 계획 승인 (Slack 외 대체 경로)"""
    body = await request.json()
    cb_id = body.get("callback_id", "")
    approved = bool(body.get("approved", False))
    resolved = resolve_approval(cb_id, approved)
    return JSONResponse({"ok": resolved, "callback_id": cb_id, "approved": approved})


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Kubernetes Liveness/Readiness probe용"""
    return JSONResponse({"status": "ok"})
