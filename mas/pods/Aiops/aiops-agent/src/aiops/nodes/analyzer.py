"""
nodes/analyzer.py — ANALYZE 노드
감지된 이벤트 + 로그 + 메트릭을 Bedrock Claude에 전달해
RCA(Root Cause Analysis) 리포트를 생성한다.

VPC2 내부에서 bedrock-runtime VPC Endpoint 경유로 호출하므로
인터넷 접근 없이도 동작한다.
"""
from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError

from ..config import settings
from ..state import AgentState

logger = logging.getLogger(__name__)

# Bedrock 클라이언트 (싱글턴)
_bedrock = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)

# ── RCA 프롬프트 템플릿 ───────────────────────────────────────────
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


def _summarize_metrics(metrics: list[dict]) -> str:
    """Prometheus 결과 상위 30개를 사람이 읽기 좋은 형태로 요약"""
    lines = []
    for m in metrics[:30]:
        metric_labels = m.get("metric", {})
        value = m.get("value", [None, "N/A"])
        values = m.get("values", [])
        last_val = values[-1][1] if values else value[-1] if len(value) > 1 else "N/A"
        name = metric_labels.get("__name__", "unknown_metric")
        pod = metric_labels.get("pod", "")
        ns = metric_labels.get("namespace", "")
        lines.append(f"{name}{{ns={ns},pod={pod}}} = {last_val}")
    return "\n".join(lines) if lines else "메트릭 없음"


async def run(state: AgentState) -> AgentState:
    """ANALYZE 노드 진입점"""
    events_str = json.dumps(state["events"], ensure_ascii=False, indent=2)
    logs_str = "\n\n".join(state["raw_logs"])[:8000]   # 토큰 제한 고려
    metrics_str = _summarize_metrics(state["raw_metrics"])

    prompt = RCA_PROMPT_TEMPLATE.format(
        events=events_str,
        logs=logs_str,
        metrics=metrics_str,
    )

    try:
        resp = _bedrock.invoke_model(
            modelId=settings.BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "temperature": 0.1,   # 낮은 temperature → 일관된 JSON 출력
                "messages": [{"role": "user", "content": prompt}],
            }),
        )
        body = json.loads(resp["body"].read())
        raw_text = body["content"][0]["text"].strip()

        # JSON 파싱 (마크다운 코드블록 제거 방어)
        if raw_text.startswith("```"):
            raw_text = "\n".join(raw_text.split("\n")[1:-1])

        rca = json.loads(raw_text)

    except (ClientError, json.JSONDecodeError, KeyError) as exc:
        logger.error("Bedrock RCA 실패: %s", exc)
        rca = {
            "root_cause": f"RCA 분석 실패: {exc}",
            "detail": "Bedrock 호출 또는 응답 파싱에 실패했습니다.",
            "evidence": [],
            "recommended_strategy": "investigate",
            "confidence": 0.0,
        }

    return {
        **state,
        "rca_report": json.dumps(rca, ensure_ascii=False, indent=2),
        "rca_root_cause": rca.get("root_cause", "알 수 없음"),
    }
