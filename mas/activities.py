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
    AuditLog,
    ComplianceReport,
    DetectThreatInput,
    ExecutionResult,
    GenerateComplianceReportInput,
    RegulationMapping,
    SecurityEvent,
)

USE_REAL_BEDROCK = os.getenv("USE_REAL_BEDROCK", "false").lower() == "true"


# =====================================================================
# 노드 로직 (secops_graph_prototype.py와 동일 — Activity가 자체 완결되도록 인라인)
# =====================================================================
def retrieve_regulations(event: SecurityEvent) -> list[str]:
    """RAG stub. 실제로는 Bedrock Knowledge Base retrieve (S3 규정 문서)."""
    return [
        "전자금융감독규정 제13조 (해킹 등 방지대책)",
        "신용정보법 제19조 (신용정보전산시스템의 안전보호)",
    ]


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


def analyze_violation(event: SecurityEvent, regulations: list[str]) -> dict:
    if not USE_REAL_BEDROCK:
        if event.destination_ip.is_private:
            return {"violated_regulations": [],
                    "violation_description": "내부 대상 트래픽 — 위반 아님(stub 판단)"}
        return {
            "violated_regulations": regulations,
            "violation_description": (
                f"{event.source_pod}가 외부 {event.destination_ip}:{event.destination_port}로 "
                "비정상 대용량 outbound. 금융 데이터 유출 정황으로 규제 위반 소지."
            ),
        }
    return _analyze_with_bedrock(event, regulations)


def _analyze_with_bedrock(event: SecurityEvent, regulations: list[str]) -> dict:
    """실제 Bedrock 호출. 에러는 계약 규칙대로 분류."""
    from botocore.exceptions import ClientError
    from shared.bedrock import ClaudeModel, get_bedrock_client

    client = get_bedrock_client()
    model_id = os.getenv("BEDROCK_MODEL", ClaudeModel.HAIKU.value)
    system_prompt = (
        "너는 금융 보안 규제 분석기다. 보안 이벤트가 제시된 규정을 위반하는지 판단해라. "
        "반드시 아래 JSON 스키마만 출력해라.\n"
        '{"violated_regulations": [string], "violation_description": string}'
    )
    user_text = (
        f"[보안 이벤트]\n{event.model_dump_json(indent=2)}\n\n"
        "[검토 대상 규정]\n" + "\n".join(f"- {r}" for r in regulations)
    )
    try:
        resp = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0},
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ValidationException":
            # 입력/모델 ID 오류 → 재시도 무의미
            raise ApplicationError(f"Bedrock ValidationException: {e}", non_retryable=True) from e
        raise  # ThrottlingException 등 → Temporal이 재시도
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    data = _parse_llm_json(text)
    return {
        "violated_regulations": list(data.get("violated_regulations", [])),
        "violation_description": str(data.get("violation_description", "")),
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
    """RAG 규정 조회 + Claude 위반 분석 + Blast Radius + 격리 정책 생성."""
    regulations = retrieve_regulations(event)
    analysis = analyze_violation(event, regulations)
    safe, detail = check_blast_radius(event)
    return RegulationMapping(
        workflow_id=event.workflow_id,           # 같은 workflow_id 전파
        violated_regulations=analysis["violated_regulations"],
        violation_description=analysis["violation_description"],
        blast_radius_safe=safe,
        blast_radius_detail=detail,
        isolation_policy_yaml=build_isolation_policy(event),
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
        severity="high",
        violated_regulations=m.violated_regulations,
        threat_summary=f"{e.threat_type} from {e.source_pod}",
        action_taken=r.action_taken,
        isolation_applied=r.success,
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


@activity.defn(name="record_audit_log")
async def record_audit_log(log: AuditLog) -> None:
    """RDS(JSONB) 감사 로그 저장. 여기선 출력만."""
    activity.logger.info("[audit] %s | %s | %s", log.event_type, log.actor, log.summary)