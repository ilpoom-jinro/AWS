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

[실시간 메트릭] (Thanos Query, 0.0~1.0 = 0~100% 비율)
CPU 사용률:    {cpu}
메모리 사용률: {memory}
에러율(5xx):   {error_rate}

[최근 로그]
{logs}

[분석 지침]
- 메트릭과 anomaly_type의 상관관계를 반드시 교차 검증하십시오.
  · oom_killed 인데 메모리 사용률이 높으면(>0.85) scale_out 신뢰도를 높이고,
    메모리가 낮은데 OOM이면 메모리 누수/limit 오설정 가능성을 의심하십시오.
  · crashloop_backoff 는 보통 로그의 예외/종료코드가 핵심 근거입니다.
    메트릭이 정상 범위면 설정/의존성 오류일 확률이 높습니다(restart 우선).
  · 에러율(5xx)이 높으면(>0.1) 단순 재시작보다 rollback을 우선 고려하십시오.
  · 메트릭이 모두 0.0이면 "수집 실패"로 간주하고 로그에 더 의존하되,
    confidence를 보수적으로 낮추십시오.
- 근거가 약하거나 상충하면 strategy를 manual로 두십시오.

[scale_out 관련 — HPA 운영 환경]
- 대상 워크로드(stock-api 등)는 HPA가 평상시 트래픽 기반 자동 스케일링을 담당합니다.
- 따라서 scale_out은 "단순 부하 증가"가 아니라, HPA가 maxReplicas 한계에 도달했는데도
  자원 부족(OOM 반복 등)이 지속되는 경우에만 선택하십시오.
  (일시적 부하는 HPA가 알아서 처리하므로 aiops 개입 불필요 → restart 또는 무개입)
- scale_out 선택 시 strategy_detail에 권장 maxReplicas 상향 목표를 함께 적으십시오.

응답 형식:
{{
  "root_cause": "한 줄 핵심 원인 (50자 이내)",
  "detail": "상세 분석 — 메트릭·로그 근거 명시 (300자 이내)",
  "confidence": 0.0~1.0,
  "strategy": "restart | scale_out | rollback | manual",
  "strategy_detail": "구체 실행 방안 (예: deployment/backend 재시작)",
  "estimated_recovery_minutes": 정수
}}"""


def _build_scale_out_directive(incident, base_detail: str) -> str:
    """scale_out을 HPA patch 방식으로 실행하도록 구조화된 지침 생성.

    대상 워크로드는 HPA가 replicas를 관리하므로 'kubectl scale'은 HPA에 의해
    되돌려진다. 대신 HPA의 maxReplicas를 상향해야 실효성이 있다.
    Platform Core execute_remediation이 파싱할 수 있도록 명시적 키=값 형태로
    실행 방식을 기록한다 (contracts 스키마 변경 없이 strategy_detail에 인코딩).

    형식 예:
      [SCALE_OUT via HPA] action=patch_hpa target_hpa=stock-api-hpa
      namespace=stock-demo maxReplicas+=2 | <LLM 근거>
    """
    deploy = _deploy_name_from_pod(incident.pod_name)
    hpa_name = f"{deploy}-hpa"
    return (
        f"[SCALE_OUT via HPA] action=patch_hpa "
        f"target_hpa={hpa_name} namespace={incident.namespace} "
        f"maxReplicas+=2 | {base_detail}"
    )


def _build_pod_directive(strategy: str, incident, base_detail: str) -> str:
    """restart/rollback을 Platform Core 파싱 형식으로 인코딩.

    Platform Core(execute_remediation)는 strategy_detail에서 pod=, namespace= 를
    파싱해 Deployment를 추론한다. namespace를 명시하지 않으면 "default"로 폴백해
    대상(stock-demo 등)을 못 찾으므로 반드시 함께 인코딩한다.
    pod_name은 RemediationPlan.pod_name 폴백도 있으나, 명시적으로 넣어 일관성 확보.

    형식:
      [RESTART]  pod=<pod> namespace=<ns> | <근거>
      [ROLLBACK] pod=<pod> namespace=<ns> | <근거>
    """
    tag = "[RESTART]" if strategy == "restart" else "[ROLLBACK]"
    return (
        f"{tag} pod={incident.pod_name} namespace={incident.namespace} "
        f"| {base_detail}"
    )


def _deploy_name_from_pod(pod_name: str) -> str:
    """파드명에서 Deployment 이름 추출 (ReplicaSet 해시 제거)."""
    import re
    parts = pod_name.rsplit("-", 2)
    if len(parts) == 3 and re.fullmatch(r"[0-9a-z]{5,10}", parts[1]):
        return parts[0]
    return pod_name


def _fmt_pct(value: float) -> str:
    """0.0~1.0 비율을 퍼센트 문자열로. 0.0은 수집 실패로 명시."""
    if value <= 0.0:
        return "0% (수집 실패 또는 데이터 없음)"
    return f"{value * 100:.1f}%"


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
        cpu=_fmt_pct(incident.cpu_usage_current),
        memory=_fmt_pct(incident.memory_usage_current),
        error_rate=_fmt_pct(incident.error_rate),
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

    # Platform Core execute_remediation이 파싱할 수 있도록 strategy_detail에
    # 실행 방식을 구조화해 명시한다 (contracts 추가 필드 없이 호환).
    # 형식은 Platform Core(mas/activities/platform.py)의 _parse_strategy_detail 규칙을 따른다:
    #   scale_out : [SCALE_OUT via HPA] action=patch_hpa target_hpa=<n> namespace=<ns> maxReplicas+=<N> | 근거
    #   restart   : [RESTART] pod=<pod> namespace=<ns> | 근거
    #   rollback  : [ROLLBACK] pod=<pod> namespace=<ns> | 근거
    # 특히 restart/rollback은 namespace를 명시하지 않으면 Platform Core가 "default"로
    # 폴백하므로, 대상 네임스페이스(stock-demo 등)를 반드시 인코딩해야 한다.
    base_detail = rca.get("strategy_detail", "")
    if strategy == "scale_out":
        strategy_detail = _build_scale_out_directive(incident, base_detail)
    elif strategy in ("restart", "rollback"):
        strategy_detail = _build_pod_directive(strategy, incident, base_detail)
    else:
        strategy_detail = base_detail

    remediation = RemediationPlan(
        workflow_id=incident.workflow_id,
        root_cause=rca.get("root_cause", "알 수 없음"),
        confidence=confidence,
        strategy=strategy,
        strategy_detail=strategy_detail,
        estimated_recovery_minutes=int(rca.get("estimated_recovery_minutes", 5)),
        rollback_available=(strategy in ("restart", "rollback", "scale_out")),
        # Platform Core가 restart/rollback 시 pod_name에서 Deployment를 추론한다
        # (연동 요청서 §2, contracts RemediationPlan.pod_name 주석).
        pod_name=incident.pod_name,
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
