"""
main.py — FastAPI 진입점

[v0.2 수정사항]
- 노드가 전부 async인데 sync invoke() 사용 → ainvoke()로 수정 (치명 버그)
- 매 사이클 initial_state()로 초기화 → messages 무한 누적(메모리 누수) 방지
- Slack url_verification(challenge) 처리 추가 — Request URL 등록 시 필요
- Slack 서명 검증(signing secret) 추가 — SLACK_SIGNING_SECRET 설정 시 활성
- request body를 한 번만 읽고 분기 (json/form 이중 읽기 문제 방지)
- 루프 예외 시 backoff 추가
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
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
_latest_state: dict = {}


# ── LangGraph 실행 루프 ───────────────────────────────────────────

async def _agent_loop() -> None:
    """SCAN_INTERVAL_SEC마다 1 사이클(monitor→…→END) 실행"""
    global _latest_state
    consecutive_errors = 0

    while True:
        try:
            # 매 사이클 새 상태로 시작 (메시지/로그 누적 방지)
            state = initial_state()
            result = await _graph.ainvoke(state)
            _latest_state = result
            consecutive_errors = 0
        except Exception as exc:
            consecutive_errors += 1
            logger.exception("에이전트 루프 오류 (%d회 연속): %s", consecutive_errors, exc)

        # 연속 실패 시 backoff (최대 5분)
        backoff = min(settings.SCAN_INTERVAL_SEC * (2 ** min(consecutive_errors, 4)), 300)
        await asyncio.sleep(backoff if consecutive_errors else settings.SCAN_INTERVAL_SEC)


# ── Slack 서명 검증 ───────────────────────────────────────────────

def _verify_slack_signature(headers, body: bytes) -> bool:
    """
    Slack Signing Secret 검증.
    SLACK_SIGNING_SECRET 미설정 시 검증 생략(개발 모드).
    """
    secret = settings.SLACK_SIGNING_SECRET
    if not secret:
        return True

    ts = headers.get("x-slack-request-timestamp", "")
    sig = headers.get("x-slack-signature", "")
    if not ts or not sig:
        return False

    try:
        if abs(time.time() - int(ts)) > 300:  # 5분 이상 차이 → replay 방지
            return False
    except ValueError:
        return False

    base = f"v0:{ts}:{body.decode('utf-8', errors='replace')}"
    expected = "v0=" + hmac.new(
        secret.encode(), base.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


# ── FastAPI 앱 ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 기동 시 Secrets 로드 → 그 다음 에이전트 루프 시작
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
async def slack_actions(request: Request):
    """
    Slack Interactivity WebHook.
    1) URL 등록 시 url_verification challenge 응답
    2) Block Kit 버튼 클릭 payload 처리 → approver Future resolve
    """
    body = await request.body()

    # 서명 검증
    if not _verify_slack_signature(request.headers, body):
        logger.warning("Slack 서명 검증 실패")
        return JSONResponse({"ok": False, "error": "invalid signature"}, status_code=401)

    # 1) JSON body → url_verification challenge (Events API 검증)
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            data = json.loads(body)
            if data.get("type") == "url_verification":
                return JSONResponse({"challenge": data.get("challenge", "")})
        except json.JSONDecodeError:
            pass

    # 2) form-urlencoded → Interactivity payload
    try:
        parsed = urllib.parse.parse_qs(body.decode("utf-8"))
        raw_payload = parsed.get("payload", ["{}"])[0]
        payload = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"ok": False, "error": "invalid payload"}, status_code=400)

    actions = payload.get("actions", [])
    if not actions:
        return JSONResponse({"ok": True})

    action = actions[0]
    # block_id는 actions[0].block_id에 위치 (Block Kit actions 블록의 block_id)
    cb_id = action.get("block_id", "") or payload.get("container", {}).get("block_id", "")
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
    """즉시 스캔 트리거"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    logger.info("수동 스캔 트리거: vpc_filter=%s", body.get("vpc_filter", "all"))
    return JSONResponse({"ok": True, "message": "스캔이 다음 주기에 실행됩니다."})


@app.get("/get-latest-rca")
async def get_latest_rca() -> JSONResponse:
    """가장 최근 RCA 리포트 반환"""
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
    """Kubernetes Liveness/Readiness probe"""
    return JSONResponse({"status": "ok"})
