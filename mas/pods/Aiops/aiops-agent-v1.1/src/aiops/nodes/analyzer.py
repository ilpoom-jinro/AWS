"""
nodes/analyzer.py — analyze_root_cause Activity 구현

AIOpsActivities.analyze_root_cause(IncidentContext) -> AnomalyReport

[MAS 정합]
- Bedrock: shared.bedrock.get_bedrock_client() + converse API (boto3 직접 호출 금지)
- 모델: ClaudeModel.SONNET (claude-sonnet-4-6)
- 출력: contracts.AnomalyReport (scenario="aiops", remediation_plan 첨부)
- 에러: ThrottlingException은 raise(Temporal retry),
        ValidationException은 ApplicationError(non_retryable=True)

LangGraph는 사용하지 않는다 — 단일 RCA 호출로 충분 (협의 결정 3).
"""
from __future__ import annotations

import json
import logging

from botocore.exceptions import ClientError
from temporalio.exceptions import ApplicationError

from contracts.models import (
    AnomalyReport,
    IncidentContext,
    RemediationPlan,
)
from shared.bedrock import ClaudeModel, get_bedrock_client

from ..mappers import to_strategy

logger = logging.getLogger(__name__)

# anomaly_type → 권장 전략 힌트 (LLM이 최종 결정하되 기본 방향 제공)
SEVERITY_BY_ANOMALY = {
    "crashloop_backoff": "high",
    "oom_killed": "high",
    "image_pull_backoff": "medium",
    "pending_timeout": "medium",
    "evicted": "high",
    "high_latency": "medium",
}

RCA_PROMPT = """당신은 쿠버네티스/AWS 인프라 전문 SRE입니다.
아래 장애를 분석하여 반드시 JSON으로만 답하십시오 (마크다운/설명 금지).

[장애]
cluster: {cluster}
namespace: {namespace}
pod: {pod}
anomaly_type: {anomaly}
restart_count: {restarts}

[최근 로그]
{logs}

응답 형식:
{{
  "root_cause": "한 줄 핵심 원인 (50자 이내)",
  "detail": "상세 분석 (300자 이내)",
  "confidence": 0.0~1.0,
  "strategy": "restart | scale_out | rollback | manual",
  "strategy_detail": "구체 실행 방안 (예: deployment/backend 재시작)",
  "estimated_recovery_minutes": 정수
}}"""


def _invoke_bedrock(prompt: str) -> dict:
    """converse API 호출 + 에러 분기. 동기 함수 (Activity가 호출)."""
    client = get_bedrock_client()
    try:
        resp = client.converse(
            modelId=ClaudeModel.SONNET.value,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.1},
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ThrottlingException":
            raise  # Temporal RetryPolicy가 재시도
        if code == "ValidationException":
            raise ApplicationError(
                f"Bedrock ValidationException: {exc}", non_retryable=True
            ) from exc
        raise

    text = resp["output"]["message"]["content"][0]["text"].strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    return json.loads(text)


async def analyze_root_cause(incident: IncidentContext) -> AnomalyReport:
    """analyze_root_cause Activity 진입점."""
    import asyncio

    prompt = RCA_PROMPT.format(
        cluster=incident.cluster_name,
        namespace=incident.namespace,
        pod=incident.pod_name,
        anomaly=incident.anomaly_type,
        restarts=incident.restart_count,
        logs="\n".join(incident.recent_logs)[:6000],
    )

    loop = asyncio.get_event_loop()
    try:
        rca = await loop.run_in_executor(None, _invoke_bedrock, prompt)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("RCA 파싱 실패: %s", exc)
        rca = {
            "root_cause": "RCA 분석 실패",
            "detail": str(exc),
            "confidence": 0.0,
            "strategy": "manual",
            "strategy_detail": "수동 조사 필요",
            "estimated_recovery_minutes": 0,
        }

    strategy = to_strategy(rca.get("strategy", "manual"))
    confidence = float(rca.get("confidence", 0.0))

    # confidence 낮으면 manual 강제
    if confidence < settings_confidence_min():
        strategy = "manual"

    remediation = RemediationPlan(
        workflow_id=incident.workflow_id,
        root_cause=rca.get("root_cause", "알 수 없음"),
        confidence=confidence,
        strategy=strategy,
        strategy_detail=rca.get("strategy_detail", ""),
        estimated_recovery_minutes=int(rca.get("estimated_recovery_minutes", 5)),
        rollback_available=(strategy in ("restart", "rollback", "scale_out")),
    )

    return AnomalyReport(
        workflow_id=incident.workflow_id,
        scenario="aiops",
        anomaly_type=incident.anomaly_type,
        severity=SEVERITY_BY_ANOMALY.get(incident.anomaly_type, "medium"),
        affected_resource=f"{incident.namespace}/{incident.pod_name}",
        summary=rca.get("root_cause", ""),
        detail=rca.get("detail", ""),
        confidence=confidence,
        remediation_plan=remediation,
    )


def settings_confidence_min() -> float:
    from ..config import settings
    return settings.RCA_CONFIDENCE_MIN
