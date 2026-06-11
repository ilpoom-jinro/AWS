"""
nodes/analyzer.py — ANALYZE 노드

[v0.2 수정사항]
- boto3 클라이언트 lazy 초기화 (import 시점 생성 → 테스트/기동 순서 문제 방지)
- Bedrock 호출을 run_in_executor로 감싸 이벤트 루프 블로킹 방지
  (boto3는 동기 SDK — async 노드 안에서 그대로 호출하면 루프 정지)
- JSON 추출 강화: 마크다운 펜스 제거 + 첫 번째 {...} 블록 정규식 추출
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from ..config import settings
from ..state import AgentState

logger = logging.getLogger(__name__)

_bedrock = None


def _get_bedrock():
    """lazy boto3 client"""
    global _bedrock
    if _bedrock is None:
        import boto3
        _bedrock = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
    return _bedrock


RCA_PROMPT_TEMPLATE = """\
당신은 쿠버네티스 및 AWS 클라우드 인프라 전문 SRE 엔지니어입니다.
아래 장애 데이터를 분석하여 반드시 다음 JSON 형식으로만 답변하십시오.
JSON 외의 텍스트(설명, 마크다운 코드블록 등)는 절대 포함하지 마십시오.

[장애 이벤트]
{events}

[파드 로그 및 K8s 이벤트 (최근 200줄)]
{logs}

[Prometheus 메트릭 요약]
{metrics}

응답 형식 (순수 JSON만):
{{
  "root_cause": "한 줄 핵심 원인 (50자 이내)",
  "detail": "상세 분석 내용 (300자 이내)",
  "evidence": ["근거 1", "근거 2", "근거 3"],
  "recommended_strategy": "restart | scale_out | rollback | investigate",
  "confidence": 0.0에서 1.0 사이의 숫자
}}
"""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

_FALLBACK_RCA = {
    "root_cause": "RCA 분석 실패",
    "detail": "Bedrock 호출 또는 응답 파싱에 실패했습니다.",
    "evidence": [],
    "recommended_strategy": "investigate",
    "confidence": 0.0,
}


def _extract_json(text: str) -> dict:
    """Bedrock 응답에서 JSON 객체 추출 (펜스/잡텍스트 방어)"""
    t = text.strip()
    if t.startswith("```"):
        # ```json ... ``` 펜스 제거
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = _JSON_BLOCK_RE.search(t)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError(f"JSON 추출 실패: {text[:200]}")


def _summarize_metrics(metrics: list[dict]) -> str:
    """Prometheus 결과 상위 30개 요약"""
    lines = []
    for m in metrics[:30]:
        labels = m.get("metric", {})
        value = m.get("value", [None, "N/A"])
        values = m.get("values", [])
        last_val = values[-1][1] if values else (value[-1] if len(value) > 1 else "N/A")
        name = labels.get("__name__", "unknown_metric")
        pod = labels.get("pod", "")
        ns = labels.get("namespace", "")
        lines.append(f"{name}{{ns={ns},pod={pod}}} = {last_val}")
    return "\n".join(lines) if lines else "메트릭 없음"


def _invoke_bedrock_sync(prompt: str) -> dict:
    """동기 Bedrock 호출 (executor 스레드에서 실행)"""
    resp = _get_bedrock().invoke_model(
        modelId=settings.BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )
    body = json.loads(resp["body"].read())
    return _extract_json(body["content"][0]["text"])


async def run(state: AgentState) -> AgentState:
    """ANALYZE 노드 진입점"""
    events_str = json.dumps(state["events"], ensure_ascii=False, indent=2)
    logs_str = "\n\n".join(state["raw_logs"])[:8000]
    metrics_str = _summarize_metrics(state["raw_metrics"])

    prompt = RCA_PROMPT_TEMPLATE.format(
        events=events_str, logs=logs_str, metrics=metrics_str
    )

    try:
        # boto3는 동기 SDK → executor 스레드로 위임해 이벤트 루프 블로킹 방지
        loop = asyncio.get_event_loop()
        rca = await loop.run_in_executor(None, _invoke_bedrock_sync, prompt)
    except Exception as exc:
        logger.error("Bedrock RCA 실패: %s", exc)
        rca = dict(_FALLBACK_RCA)
        rca["detail"] = f"{rca['detail']} ({exc})"

    return {
        **state,
        "rca_report": json.dumps(rca, ensure_ascii=False, indent=2),
        "rca_root_cause": rca.get("root_cause", "알 수 없음"),
    }
