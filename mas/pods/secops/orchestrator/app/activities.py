"""
SecOps Temporal Activities
==========================
계약(contracts/activity_interfaces.py)의 SecOpsActivities + 공통 Activity 구현.

핵심 규칙 (contracts 주석 그대로):
    - 입출력은 contracts/models.py의 Pydantic 모델만 사용
    - Activity 내부에서만 I/O(Bedrock, k8s, DB) 수행 — Workflow는 I/O 금지
    - Bedrock ValidationException → ApplicationError(non_retryable=True)
      ThrottlingException 등 → 그냥 raise (Temporal RetryPolicy가 재시도)
    - apply_isolation은 상태 변경 Activity → 멱등성 + heartbeat 패턴

지금은 RAG/Slack/격리/감사 저장이 stub. map_regulation의 Claude만 실제 호출 가능.
"""

from __future__ import annotations

import json
import os

from temporalio import activity
from temporalio.exceptions import ApplicationError

from contracts.models import (
    ApprovalRequest,
    ApprovalTicket,
    ComplianceReport,
    DetectThreatInput,
    ExecutionResult,
    GenerateComplianceReportInput,
    RegulationMapping,
    SecurityEvent,
)

from .retrieval import RetrievedChunk, get_retriever
from activities.platform import record_audit_log

USE_REAL_BEDROCK = os.getenv("USE_REAL_BEDROCK", "false").lower() == "true"
# 1차 triage (Nova Lite / Haiku): 저비용 필터 — 위협 아닌 이벤트를 조기 차단해 Sonnet 비용 통제
BEDROCK_MODEL_LIGHT = os.getenv("BEDROCK_MODEL_LIGHT", "amazon.nova-lite-v1:0")
# 2차 최종 판단 (Sonnet): 1차 통과분만 호출
BEDROCK_MODEL = os.getenv("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6-20251001-v1:0")

# 이벤트 → 규정 검색 쿼리 키워드 (한국어 규정 본문과 매칭되도록)
THREAT_QUERY_TERMS = {
    "abnormal_outbound": "비정상 외부 송신 트래픽 데이터 유출 outbound",
    "data_exfiltration": "데이터 유출 외부 반출 대량 전송 신용정보 개인정보",
    "port_scan": "포트 스캔 침입 비정상 접근 탐지 차단",
    "policy_violation": "정책 위반 접근통제 비인가 통신",
}


# =====================================================================
# 노드 로직 (secops_graph_prototype.py와 동일 — Activity가 자체 완결되도록 인라인)
# =====================================================================
def _build_query(event: SecurityEvent) -> str:
    terms = THREAT_QUERY_TERMS.get(event.threat_type, "")
    return f"{terms} {event.direction} {event.destination_ip} {event.raw_log}"


def retrieve_regulations(event: SecurityEvent) -> list[RetrievedChunk]:
    """
    RAG 검색. 백엔드는 retrieval.get_retriever()가 env로 선택:
        기본 = LocalRegulationRetriever (레포 안 규정 발췌, 발표 시연용)
        USE_BEDROCK_KB=true = BedrockKBRetriever (실제 KB)
    """
    return get_retriever().retrieve(_build_query(event), top_k=3)


def _parse_llm_json(text: str) -> dict:
    payload = text.strip()
    if payload.startswith("```"):
        payload = payload.strip("`").strip()
        if payload.lower().startswith("json"):
            payload = payload[4:].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        s, e = payload.find("{"), payload.rfind("}")
        return json.loads(payload[s : e + 1])


def analyze_violation(event: SecurityEvent, chunks: list[RetrievedChunk]) -> dict:
    """위반 분석. USE_REAL_BEDROCK=false면 stub, true면 2단계 Bedrock 호출."""
    if not USE_REAL_BEDROCK:
        if event.destination_ip.is_private:
            return {
                "violated_regulations": [],
                "violation_description": "내부 대상 트래픽 — 위반 아님(stub 판단)",
                "confidence": 0.9,
                "severity": "low",
                "evidence": {},
            }
        # 검색된 규정 근거를 그대로 인용해 판단에 박는다 (화면에 보이는 RAG 근거)
        sources = list(dict.fromkeys(c.source for c in chunks)) or ["(검색 결과 없음)"]
        evidence_note = ""
        if chunks:
            top = chunks[0]
            evidence_note = (f" 검색된 규정 근거 — 「{top.source}」: "
                             f"\"{top.text[:120].strip()}…\" (관련도 {top.score}).")
        return {
            "violated_regulations": sources,
            "violation_description": (
                f"{event.source_pod}가 외부 {event.destination_ip}:{event.destination_port}로 "
                f"비정상 대용량 outbound 전송.{evidence_note} 데이터 유출 정황으로 위 규정 위반 소지."
            ),
            "confidence": 0.75,
            "severity": "high",
            "evidence": {
                "source": "stub",
                "source_pod": event.source_pod,
                "destination": f"{event.destination_ip}:{event.destination_port}",
                "threat_type": event.threat_type,
                "raw_log": event.raw_log[:200],
            },
        }
    # Real Bedrock: 1차(Nova Lite) → 필터 통과 시 2차(Sonnet) 최종 판정
    triage = _triage_with_bedrock(event, chunks)
    if not triage["is_threat"]:
        return {
            "violated_regulations": [],
            "violation_description": (
                f"1차 판단({BEDROCK_MODEL_LIGHT}): 위협 아님 "
                f"(confidence={triage['confidence']:.0%})"
            ),
            "confidence": triage["confidence"],
            "severity": triage["severity"],
            "evidence": {"triage_model": BEDROCK_MODEL_LIGHT},
        }
    return _analyze_with_bedrock(event, chunks)


def _triage_with_bedrock(event: SecurityEvent, chunks: list[RetrievedChunk]) -> dict:
    """1차 판단 (Nova Lite): 위협 여부 + confidence + severity 빠른 필터.
    is_threat=False면 Sonnet 호출 생략 — 비용 통제 핵심."""
    from botocore.exceptions import ClientError
    from shared.bedrock import get_bedrock_client

    client = get_bedrock_client()
    grounding = "\n\n".join(
        f"[{c.source}] (관련도 {c.score})\n{c.text[:300]}" for c in chunks
    ) or "(검색 결과 없음)"
    system_prompt = (
        "너는 보안 이벤트 사전 분류기다. 아래 이벤트가 금융 규제 위반 가능성이 있는지 빠르게 판단해라. "
        "반드시 아래 JSON만 출력해라.\n"
        '{"is_threat": bool, "confidence": float, "severity": "critical"|"high"|"medium"|"low"}'
    )
    user_text = (
        f"[보안 이벤트 요약]\n"
        f"threat_type={event.threat_type} source_pod={event.source_pod} "
        f"destination={event.destination_ip}:{event.destination_port} "
        f"direction={event.direction}\n\n"
        f"[규정 근거 요약]\n{grounding}"
    )
    try:
        resp = client.converse(
            modelId=BEDROCK_MODEL_LIGHT,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"maxTokens": 256, "temperature": 0},
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ValidationException":
            raise ApplicationError(
                f"Bedrock triage ValidationException: {e}", non_retryable=True
            ) from e
        raise
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    data = _parse_llm_json(text)
    return {
        "is_threat": bool(data.get("is_threat", True)),
        "confidence": float(data.get("confidence", 0.5)),
        "severity": str(data.get("severity", "medium")),
    }


def _analyze_with_bedrock(event: SecurityEvent, chunks: list[RetrievedChunk]) -> dict:
    """2차 최종 판단 (Sonnet): 위반 규정 + 설명 + confidence + severity + evidence.
    1차 triage 통과분만 호출 — Sonnet 비용이 Nova의 ~85×이므로 반드시 필터 후 진입."""
    from botocore.exceptions import ClientError
    from shared.bedrock import get_bedrock_client

    client = get_bedrock_client()
    system_prompt = (
        "너는 금융 보안 규제 분석기다. 보안 이벤트가 '검색된 규정 근거'를 위반하는지, "
        "반드시 그 근거에 기반해 판단해라. 근거에 없는 규정은 지어내지 마라. "
        "반드시 아래 JSON 스키마만 출력해라.\n"
        '{"violated_regulations": [string], "violation_description": string, '
        '"confidence": float, "severity": "critical"|"high"|"medium"|"low", '
        '"evidence": {"event_id": string, "source": string, "detail": string}}'
    )
    grounding = "\n\n".join(
        f"[{c.source}] (관련도 {c.score})\n{c.text}" for c in chunks
    ) or "(검색 결과 없음)"
    user_text = (
        f"[보안 이벤트]\n{event.model_dump_json(indent=2)}\n\n"
        f"[검색된 규정 근거]\n{grounding}"
    )
    try:
        resp = client.converse(
            modelId=BEDROCK_MODEL,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0},
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ValidationException":
            raise ApplicationError(f"Bedrock ValidationException: {e}", non_retryable=True) from e
        raise
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    data = _parse_llm_json(text)
    return {
        "violated_regulations": list(data.get("violated_regulations", [])),
        "violation_description": str(data.get("violation_description", "")),
        "confidence": float(data.get("confidence", 0.8)),
        "severity": str(data.get("severity", "high")),
        "evidence": dict(data.get("evidence", {})),
    }


def check_blast_radius(event: SecurityEvent) -> tuple[bool, str]:
    safe = event.namespace != "kube-system"
    detail = ("단일 worker pod 격리, 동일 서비스 다른 replica가 처리 가능 → 안전"
              if safe else "시스템 네임스페이스(kube-system) 영향 → 위험")
    return safe, detail


def build_isolation_policy(event: SecurityEvent) -> str:
    """Istio AuthorizationPolicy (민수님 확인: 이 프로젝트는 Istio)."""
    return f"""apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: isolate-{event.source_pod}
  namespace: {event.namespace}
spec:
  selector:
    matchLabels:
      pod: {event.source_pod}
  action: DENY
  rules:
    - {{}}
"""


# =====================================================================
# Activities (Worker 등록 대상)
#   name=은 workflows/activity_options.py의 ActivityName 값과 일치시킴
# =====================================================================
@activity.defn(name="detect_threat")
async def detect_threat(input: DetectThreatInput) -> SecurityEvent:
    """VPC Flow Logs/CloudTrail 탐지. 여기선 외부 유출 더미 이벤트 생성."""
    # TODO(실제): boto3로 VPC Flow Logs 조회. 지금은 탐지됐다고 가정.
    event = SecurityEvent(
        cluster_name=input.cluster_name,         # SecurityEvent가 workflow_id 최초 생성
        namespace="financial-api",
        source_pod="payment-worker-7d9f",
        source_ip="10.0.12.34",
        destination_ip="104.18.0.1",             # 공인 IP (외부 유출)
        destination_port=8443,
        protocol="tcp",
        direction="outbound",
        threat_type="abnormal_outbound",
        raw_log="[flowlog] 10.0.12.34 -> 104.18.0.1:8443 ACCEPT 1.2MB/5s",
    )
    activity.logger.info("threat detected: workflow_id=%s", event.workflow_id)
    return event


@activity.defn(name="map_regulation")
async def map_regulation(event: SecurityEvent) -> RegulationMapping:
    """RAG 규정 조회 + 2단계 Bedrock 판단(Nova→Sonnet) + Blast Radius + 격리 정책 생성."""
    chunks = retrieve_regulations(event)
    analysis = analyze_violation(event, chunks)
    safe, detail = check_blast_radius(event)
    return RegulationMapping(
        workflow_id=event.workflow_id,
        violated_regulations=analysis["violated_regulations"],
        violation_description=analysis["violation_description"],
        blast_radius_safe=safe,
        blast_radius_detail=detail,
        isolation_policy_yaml=build_isolation_policy(event),
        confidence=analysis.get("confidence", 0.0),
        severity=analysis.get("severity", "low"),
        evidence=analysis.get("evidence", {}),
    )


@activity.defn(name="apply_isolation")
async def apply_isolation(mapping: RegulationMapping) -> ExecutionResult:
    """
    Istio 정책 적용. 권한상 Platform Core 소유 (여기선 stub).
    상태 변경 Activity → heartbeat 호출 + 멱등 구현 필요.
    """
    activity.heartbeat("applying isolation policy")
    # TODO(실제, 민수님 PR 리뷰): k8s client로 mapping.isolation_policy_yaml apply (멱등)
    return ExecutionResult(
        workflow_id=mapping.workflow_id,
        success=True,
        action_taken="Istio AuthorizationPolicy 적용으로 pod 격리 (stub)",
        output="isolated",
    )


@activity.defn(name="generate_compliance_report")
async def generate_compliance_report(input: GenerateComplianceReportInput) -> ComplianceReport:
    """event + mapping + 실행결과 → 규제 대응 보고서."""
    e, m, r = input.event, input.mapping, input.result
    return ComplianceReport(
        workflow_id=e.workflow_id,
        severity=m.severity,
        violated_regulations=m.violated_regulations,
        threat_summary=f"{e.threat_type} from {e.source_pod}",
        action_taken=r.action_taken,
        isolation_applied=r.success,
        confidence=m.confidence,
        evidence=m.evidence,
    )


# ---- 공통 Activity (실제 구현은 민수님 / slack-hitl) ----
@activity.defn(name="send_approval_request")
async def send_approval_request(request: ApprovalRequest) -> ApprovalTicket:
    """Slack 승인 메시지 전송 후 티켓 반환. 즉시 반환 (대기는 Workflow가 signal로)."""
    activity.logger.info("Slack 승인 요청(stub): %s", request.summary)
    # TODO(실제): Slack chat.postMessage → ts/channel 반환
    return ApprovalTicket(
        workflow_id=request.workflow_id,
        slack_message_ts="1718000000.000100",
        channel_id="C_SECOPS_STUB",
    )
