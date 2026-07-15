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

import asyncio
import json
import os
import re
from datetime import datetime, timedelta

from temporalio import activity
from temporalio.exceptions import ApplicationError

from contracts.models import (
    ApprovalRequest,
    ApprovalTicket,
    ComplianceReport,
    DetectThreatInput,
    ExecutionResult,
    GenerateComplianceReportInput,
    GeneratePostMortemReportInput,
    IncidentGroup,
    PostMortemReport,
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
# 계정 탈취 인과판정(3차, Sonnet) — list-inference-profiles로 확인된 값. 접두사 없는
# "anthropic.claude-sonnet-4-6"은 on-demand 직접 호출 불가(Nova 때와 동일한 문제).
BEDROCK_MODEL_SONNET = os.getenv("BEDROCK_MODEL_SONNET", "global.anthropic.claude-sonnet-4-6")

# 이벤트 → 규정 검색 쿼리 키워드 (한국어 규정 본문과 매칭되도록)
THREAT_QUERY_TERMS = {
    "abnormal_outbound": "비정상 외부 송신 트래픽 데이터 유출 outbound",
    "data_exfiltration": "데이터 유출 외부 반출 대량 전송 신용정보 개인정보",
    "port_scan": "포트 스캔 침입 비정상 접근 탐지 차단",
    "policy_violation": "정책 위반 접근통제 비인가 통신",
    "lateral_movement": "측면 이동 내부 확산 비정상 파드간 통신 침해 확산",
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
    from .detection import extract_evidence

    client = get_bedrock_client()
    grounding = "\n\n".join(
        f"[{c.source}] (관련도 {c.score})\n{c.text[:300]}" for c in chunks
    ) or "(검색 결과 없음)"
    system_prompt = (
        "너는 보안 이벤트 사전 분류기다. 아래 이벤트가 금융 규제 위반 가능성이 있는지 빠르게 판단해라. "
        "AdministratorAccess/PowerUserAccess/IAMFullAccess 같은 고권한 정책 부여, AccessKey 생성 등은 "
        "권한 상승·계정 탈취 징후이므로 severity를 높게 판단해라. "
        "반드시 아래 JSON만 출력해라.\n"
        '{"is_threat": bool, "confidence": float, "severity": "critical"|"high"|"medium"|"low"}'
    )
    evidence = extract_evidence(event)
    if event.event_source == "cloudtrail" or evidence.get("event_name"):
        # IAM(CloudTrail) 이벤트 — source_pod/destination_ip 등 network 필드는
        # unknown/무의미하므로 IAM 컨텍스트로 대체
        target = (
            evidence.get("target_user")
            or evidence.get("target_role")
            or evidence.get("target_group")
            or ""
        )
        user_text = (
            f"[IAM 보안 이벤트]\n"
            f"event_name={evidence.get('event_name', '')} 대상={target}\n"
            f"부여된 정책={evidence.get('policy_arn', '')}\n"
            f"행위자={evidence.get('user_arn', '')}\n"
            f"threat_type={event.threat_type}\n\n"
            f"[규정 근거 요약]\n{grounding}"
        )
    else:
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
    from .detection import extract_evidence

    client = get_bedrock_client()
    system_prompt = (
        "너는 금융 보안 규제 분석기다. 보안 이벤트가 '검색된 규정 근거'를 위반하는지, "
        "반드시 그 근거에 기반해 판단해라. 근거에 없는 규정은 지어내지 마라. "
        "AdministratorAccess/PowerUserAccess/IAMFullAccess 같은 고권한 정책 부여, AccessKey 생성 등은 "
        "권한 상승·계정 탈취 징후이므로 severity를 높게 판단해라. "
        "반드시 아래 JSON 스키마만 출력해라.\n"
        '{"violated_regulations": [string], "violation_description": string, '
        '"confidence": float, "severity": "critical"|"high"|"medium"|"low", '
        '"evidence": {"event_id": string, "source": string, "detail": string}}'
    )
    grounding = "\n\n".join(
        f"[{c.source}] (관련도 {c.score})\n{c.text}" for c in chunks
    ) or "(검색 결과 없음)"
    # event.model_dump_json에 raw_log(evidence 원문 포함)가 실려는 있으나 텍스트 블록이라
    # LLM이 놓칠 수 있어, IAM 이벤트는 구조화된 필드를 명시적으로 덧붙여 명확히 한다.
    iam_context = ""
    if event.event_source == "cloudtrail":
        evidence = extract_evidence(event)
        target = (
            evidence.get("target_user")
            or evidence.get("target_role")
            or evidence.get("target_group")
            or ""
        )
        iam_context = (
            f"\n\n[IAM 컨텍스트]\n"
            f"event_name={evidence.get('event_name', '')} 대상={target}\n"
            f"부여된 정책={evidence.get('policy_arn', '')}\n"
            f"행위자={evidence.get('user_arn', '')}"
        )
    user_text = (
        f"[보안 이벤트]\n{event.model_dump_json(indent=2)}"
        f"{iam_context}\n\n"
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


SENSITIVE_NAMESPACES = {"kube-system", "istio-system", "kube-public", "kube-node-lease"}

# 단일 pod 격리로 흡수 불가한(공유·인프라·상태ful) 컴포넌트 힌트 — pod 이름 부분매칭
SHARED_COMPONENT_HINTS = (
    "db", "database", "postgres", "mysql", "redis", "cache", "kafka", "queue",
    "gateway", "ingress", "proxy", "lb", "loadbalancer", "auth", "identity",
)


def check_blast_radius(event: SecurityEvent) -> tuple[bool, str, dict]:
    """
    다요인 blast radius 판정.
    반환: (safe, detail 서술, evidence dict — 판정 근거 구조화)

    요인별 위험 가중치를 합산해 score(0~1)를 내고, 임계치로 safe/level을 정한다.
    (계약 필드는 그대로 — 근거는 evidence["blast_radius"]에 담아 보고서/감사로그에 활용)
    """
    factors: list[dict] = []
    score = 0.0

    # 1) 민감/시스템 네임스페이스 — 격리 시 클러스터 전반 영향
    ns = event.namespace
    if ns in SENSITIVE_NAMESPACES:
        factors.append({"factor": "sensitive_namespace", "value": ns, "weight": 0.7})
        score += 0.7
    elif ns.endswith("-system") or ns.endswith("-infra"):
        factors.append({"factor": "infra_namespace", "value": ns, "weight": 0.5})
        score += 0.5

    # 2) 대상 pod가 공유/상태ful 컴포넌트 — 다른 replica가 흡수 못 함 (단일 요인으로도 위험)
    pod_l = event.source_pod.lower()
    hit = next((h for h in SHARED_COMPONENT_HINTS if h in pod_l), None)
    if hit:
        factors.append({"factor": "shared_component", "value": f"'{hit}' in {event.source_pod}", "weight": 0.5})
        score += 0.5

    # 3) inbound 위협 — 격리해도 외부 유입 경로가 남을 수 있어 영향 판단 가중
    if event.direction == "inbound":
        factors.append({"factor": "inbound_direction", "value": "inbound", "weight": 0.3})
        score += 0.3

    # 4) 위협 유형 가중 (port_scan/policy_violation/lateral_movement은 단일 격리로
    #    충분치 않을 수 있음 — lateral_movement는 port_scan과 동일 가중치로 시작,
    #    실측 후 조정 대상)
    if event.threat_type in ("port_scan", "policy_violation", "lateral_movement"):
        factors.append({"factor": "threat_type", "value": event.threat_type, "weight": 0.3})
        score += 0.3

    score = round(min(score, 1.0), 2)
    # 위험 요인 점수 합이 임계치 미만이면 "단일 pod 격리로 흡수 가능 → 안전"
    safe = score < 0.5
    level = "low" if score < 0.5 else ("high" if score >= 0.8 else "medium")

    if safe:
        detail = (f"단일 worker pod({event.source_pod}) 격리, 동일 서비스 다른 replica가 처리 가능 "
                  f"→ 안전 (blast score={score})")
    else:
        reasons = ", ".join(f["factor"] for f in factors) or "복합 요인"
        detail = (f"격리 영향 범위 위험 (blast score={score}, level={level}) — {reasons}. "
                  f"자동 격리 전 검토 필요")

    evidence = {
        "blast_radius": {
            "score": score,
            "level": level,
            "safe": safe,
            "factors": factors,
            "namespace": ns,
            "source_pod": event.source_pod,
        }
    }
    return safe, detail, evidence


def build_isolation_policy(event: SecurityEvent) -> str:
    """
    격리용 CiliumNetworkPolicy 생성 (민수님 확인: 이 프로젝트는 Cilium enforce).

    Cilium은 endpoint에 정책이 매칭되고 허용 규칙이 없으면 차단한다. 여기서는
    레포의 default-deny.yaml과 동일하게 enableDefaultDeny(ingress/egress true)를
    명시해, 대상 pod의 모든 in/out 트래픽을 확실히 차단한다(Istio DENY와 동일 효과).

    네임스페이스 스코프(CiliumNetworkPolicy)로 생성해 대상 워크로드가 있는 ns에만 적용.

    워크로드 단위 격리(B-1): endpointSelector는 event.isolation_labels(Hubble
    source.labels에서 뽑은 app.kubernetes.io/name+instance)를 그대로 쓴다.
    source_pod는 Pod 이름이라 재기동마다 바뀌고 "pod" 자체가 표준 레이블도 아니라
    격리 셀렉터로 못 쓴다(증거 표시용으로만 event에 남아 있음).
    """
    if not event.isolation_labels:
        # 빈 matchLabels로 CNP를 만들면 네임스페이스의 모든 endpoint에 매칭돼
        # 의도치 않은 전체 격리로 번질 수 있다 — 그 사고를 막는 방어적 중단.
        raise ApplicationError(
            f"격리 셀렉터 없음 — isolation_labels가 비어 있어 격리를 중단한다 "
            f"(source_pod={event.source_pod}, namespace={event.namespace})",
            non_retryable=True,
        )
    match_labels = "\n".join(f"      {k}: {v}" for k, v in event.isolation_labels.items())
    return f"""apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: isolate-{event.workload_name}
  namespace: {event.namespace}
  labels:
    app.kubernetes.io/managed-by: secops-mas
    secops.mas/isolation: "true"
spec:
  description: "SecOps 자동 격리 - {event.workload_name} ({event.threat_type})"
  endpointSelector:
    matchLabels:
{match_labels}
  enableDefaultDeny:
    ingress: true
    egress: true
"""


# =====================================================================
# Activities (Worker 등록 대상)
#   name=은 workflows/activity_options.py의 ActivityName 값과 일치시킴
# =====================================================================
@activity.defn(name="detect_threat")
async def detect_threat(input: DetectThreatInput) -> SecurityEvent:
    """트리거 메시지가 있으면 파싱·보강, 없으면(run_demo/수동) 더미 이벤트 생성."""
    if input.trigger_message:
        from .detection import message_to_event
        from .telemetry import enrich_flow_logs
        # message_to_event는 enrich_flow_logs(동기 boto3 CloudWatch Insights, 폴링)를 부를 수 있어
        # to_thread로 오프로드 — 이벤트 루프(uvicorn /health) 블로킹 방지.
        event = await asyncio.to_thread(
            message_to_event, input.trigger_message, input.cluster_name, enrich_flow_logs
        )
        if event is not None:
            activity.logger.info("threat parsed from trigger: workflow_id=%s source=%s",
                                 event.workflow_id, event.event_source)
            return event
        activity.logger.warning("trigger 파싱 실패 → 더미로 폴백")
    # 폴백/데모: 명백한 데이터 유출 시나리오 (AI가 high로 판단 → Slack 승인·격리 시연)
    event = SecurityEvent(
        cluster_name=input.cluster_name,         # SecurityEvent가 workflow_id 최초 생성
        namespace="financial-api",
        source_pod="payment-worker-7d9f",
        # 워크로드 단위 격리(B-1) 대응 — 이 데모가 apply_isolation까지 실제로 타는
        # 유일한 경로라, 예전처럼 존재하지 않는 "pod" 레이블 대신 실제 표준
        # 레이블(app.kubernetes.io/name+instance)로 채워야 격리가 헛돌지 않는다.
        workload_name="payment-worker",
        workload_kind="Deployment",
        isolation_labels={
            "app.kubernetes.io/name": "payment-worker",
            "app.kubernetes.io/instance": "payment-worker",
        },
        source_ip="10.0.12.34",
        destination_ip="185.220.101.47",         # 외부 미상 IP (Tor exit 대역대 성격)
        destination_port=8443,
        protocol="tcp",
        direction="outbound",
        threat_type="data_exfiltration",
        raw_log=(
            "[flowlog] 10.0.12.34 -> 185.220.101.47:8443 ACCEPT 847MB/32s "
            "| payment-worker-7d9f가 카드결제 DB(신용정보) 대량 조회 직후 외부 미상 IP로 "
            "847MB 대량 outbound 전송 감지 — 정상 업무 트래픽 대비 400배 급증, 데이터 유출 정황"
        ),
    )
    activity.logger.info("threat detected (dummy): workflow_id=%s", event.workflow_id)
    return event


@activity.defn(name="map_regulation")
async def map_regulation(event: SecurityEvent) -> RegulationMapping:
    """RAG 규정 조회 + 2단계 Bedrock 판단(Nova→Sonnet) + Blast Radius + 격리 정책 생성."""
    # Bedrock KB retrieve / LLM converse는 동기 boto3 → to_thread로 오프로드해야
    # 이벤트 루프(같은 프로세스의 uvicorn /health)가 막히지 않는다. (안 하면 프로브 timeout→CrashLoop)
    chunks = await asyncio.to_thread(retrieve_regulations, event)
    analysis = await asyncio.to_thread(analyze_violation, event, chunks)
    safe, detail, blast_evidence = check_blast_radius(event)
    # 분석 evidence + blast radius + 트리거 증적(raw_log에 실려온 CloudTrail Event ID 등) 병합
    from .detection import extract_evidence
    evidence = {**analysis.get("evidence", {}), **blast_evidence, **extract_evidence(event)}
    # IAM(계정 탈취) 이벤트는 isolation_labels가 없다(그 경로는 revoke_iam_privilege가
    # 대응하지, Cilium 격리를 안 씀) — build_isolation_policy는 이제 그 경우 ApplicationError를
    # 내므로, map_regulation 자체는 모든 이벤트에 대해 여전히 성공해야 해 여기서 미리 분기한다.
    # 리스트인 이유: 워크로드 건너가는 사슬(A→B)이 확정되면 workflow.py가 여러 이벤트의
    # isolation_policy_yaml을 합쳐 apply_isolation에 한 번에 넘긴다(단일 이벤트는 원소 1개).
    isolation_policy_yaml = [build_isolation_policy(event)] if event.isolation_labels else []
    return RegulationMapping(
        workflow_id=event.workflow_id,
        violated_regulations=analysis["violated_regulations"],
        violation_description=analysis["violation_description"],
        blast_radius_safe=safe,
        blast_radius_detail=detail,
        isolation_policy_yaml=isolation_policy_yaml,
        confidence=analysis.get("confidence", 0.0),
        severity=analysis.get("severity", "low"),
        evidence=evidence,
    )


def _load_k8s_config() -> None:
    """in-cluster(배포 Pod) 우선, 실패 시 kubeconfig(로컬). 둘 다 없으면 ConfigException."""
    from kubernetes import config
    from kubernetes.config.config_exception import ConfigException
    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config()   # kubeconfig도 없으면 ConfigException 재발생


def _apply_isolation_policy(doc: dict, dry_run: bool = False) -> str:
    """
    CiliumNetworkPolicy를 멱등 apply (create; 이미 있으면 replace). 반환 'created'|'replaced'.
    dry_run=True면 k8s API 서버측 dry_run="All"로 검증만 수행(실제 반영 없음).
    """
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    group, version = doc["apiVersion"].split("/", 1)   # cilium.io, v2
    plural = "ciliumnetworkpolicies"
    ns = doc["metadata"].get("namespace") or "default"
    name = doc["metadata"]["name"]
    api = client.CustomObjectsApi()
    kwargs = {"dry_run": "All"} if dry_run else {}
    try:
        api.create_namespaced_custom_object(group, version, ns, plural, doc, **kwargs)
        return "created"
    except ApiException as exc:
        if exc.status != 409:            # 409=이미 존재 → replace로 멱등, 그 외는 전파(재시도)
            raise
        existing = api.get_namespaced_custom_object(group, version, ns, plural, name)
        doc["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
        api.replace_namespaced_custom_object(group, version, ns, plural, name, doc, **kwargs)
        return "replaced"


@activity.defn(name="apply_isolation")
async def apply_isolation(mapping: RegulationMapping, dry_run: bool = False) -> ExecutionResult:
    """
    CiliumNetworkPolicy(mapping.isolation_policy_yaml, 워크로드당 1개씩 리스트)를 전부
    클러스터에 멱등 적용. 워크로드 건너가는 사슬(A→B)이 확정되면 여러 워크로드를 동시에
    격리해야 하므로 리스트 전체를 순회한다(단일 워크로드면 원소 1개, 기존과 동일 동작).
      - dry_run=True (1단계 검증 호출): k8s API 서버측 dry_run="All"로 검증만, 미반영
      - dry_run=False (2단계 실apply 호출): in-cluster 자격증명으로 실제 apply (create-or-replace)
      - 로컬/발표(클러스터 미연결) 또는 ISOLATION_DRY_RUN=true: dry_run 인자와 무관하게 항상
        canned dry-run(정책 검증만, 미적용) — 기존 안전망 그대로 유지
    상태 변경 Activity → heartbeat. 동기 k8s 호출은 스레드로 오프로드(이벤트 루프 비차단).
    """
    import yaml

    activity.heartbeat("apply_isolation: start")
    docs = [d for d in (yaml.safe_load(p) for p in mapping.isolation_policy_yaml) if d]
    if not docs:
        # map_regulation은 isolation_labels 없는 이벤트(예: IAM 대응 — revoke_iam_privilege가
        # 처리하지 Cilium 격리 대상이 아님)엔 isolation_policy_yaml=[]을 반환한다. 그 상태로
        # 여기까지 왔다는 건 라우팅이 잘못됐거나 워크로드 레이블이 아직 안 채워진 것 —
        # 재시도로 낭비하지 않고 바로 실패시켜 원인을 드러낸다.
        raise ApplicationError(
            f"apply_isolation: isolation_policy_yaml 없음(workflow_id={mapping.workflow_id}) "
            f"— 격리 대상 워크로드 레이블이 없는 이벤트가 apply_isolation으로 들어옴",
            non_retryable=True,
        )
    targets = [
        f"{d.get('metadata', {}).get('name', '?')}(ns={d.get('metadata', {}).get('namespace', 'default')})"
        for d in docs
    ]
    targets_str = ", ".join(targets)

    force_dry_run = os.getenv("ISOLATION_DRY_RUN", "").lower() == "true"
    no_cluster = False
    if not force_dry_run:
        from kubernetes.config.config_exception import ConfigException
        try:
            await asyncio.to_thread(_load_k8s_config)
        except ConfigException:
            # 클러스터 설정 없음(로컬/발표자 PC)만 dry-run. 그 외(패키지 미설치·네트워크 등)는 전파.
            no_cluster = True

    if force_dry_run or no_cluster:
        return ExecutionResult(
            workflow_id=mapping.workflow_id,
            success=True,
            action_taken=f"[DRY-RUN] CiliumNetworkPolicy {len(docs)}건({targets_str}) 검증 완료 — 클러스터 미적용",
            output="\n".join(mapping.isolation_policy_yaml),
        )

    if dry_run:
        activity.heartbeat("apply_isolation: server-side dry-run")
        for doc in docs:
            await asyncio.to_thread(_apply_isolation_policy, doc, True)
        return ExecutionResult(
            workflow_id=mapping.workflow_id,
            success=True,
            action_taken=f"[DRY-RUN] CiliumNetworkPolicy {len(docs)}건({targets_str}) 서버 검증 완료 — 클러스터 미적용",
            output="\n".join(mapping.isolation_policy_yaml),
        )

    activity.heartbeat("apply_isolation: applying")
    outcomes = []
    for doc in docs:
        name = doc.get("metadata", {}).get("name", "?")
        ns = doc.get("metadata", {}).get("namespace", "default")
        outcome = await asyncio.to_thread(_apply_isolation_policy, doc, False)
        outcomes.append(f"{outcome}: {name} (ns={ns})")
        activity.heartbeat(f"apply_isolation: applied {len(outcomes)}/{len(docs)}")
    return ExecutionResult(
        workflow_id=mapping.workflow_id,
        success=True,
        action_taken=f"CiliumNetworkPolicy {len(docs)}건 적용 — pod 격리 적용: {', '.join(outcomes)}",
        output="\n".join(outcomes),
    )


# ops VPC(IGW/NAT 없음) + IAM은 ap-northeast-2 PrivateLink 미지원(us-east-1 전용)이라
# orchestrator가 IAM을 직접 호출할 수 없다 — 실제 detach/update는 VPC 밖 Lambda
# (financial-secops-iam-responder, secops-iam-responder.tf)에 위임한다. Lambda 안에
# 원래 이 함수가 하던 _revoke_iam_privilege 로직이 그대로 옮겨가 있다
# (lambda/secops-iam-responder/handler.py — 순수 dict→str 함수라 이식이 쉬웠다).
def _invoke_iam_responder_lambda(evidence: dict) -> str:
    """financial-secops-iam-responder Lambda를 동기 호출(RequestResponse)해 실제 IAM
    detach/deactivate를 실행시킨다. Lambda invoke는 vpc/ops/endpoints.tf의 Lambda
    Interface Endpoint를 거쳐야 하고(없으면 IAM 직접 호출과 동일하게 connect timeout),
    이 호출 자체는 짧아 heartbeat 불필요(apply_isolation류와 달리 여러 단계 없음).
    """
    import boto3

    function_name = os.getenv("SECOPS_IAM_RESPONDER_FUNCTION_NAME", "financial-secops-iam-responder")
    region = os.getenv("AWS_REGION", "ap-northeast-2")

    lambda_client = boto3.client("lambda", region_name=region)
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({"evidence": evidence, "dry_run": False}).encode("utf-8"),
    )

    payload = json.loads(response["Payload"].read())
    if response.get("FunctionError"):
        raise RuntimeError(f"IAM 회수 Lambda 실행 오류({response['FunctionError']}): {payload}")
    if not payload.get("success"):
        raise ValueError(payload.get("action_taken", "IAM 회수 Lambda가 실패를 보고함"))
    return payload["action_taken"]


def _describe_iam_action(evidence: dict) -> str | None:
    """실행 전 '무엇을 할지' 설명 문자열. 지원 대상이 아니면 None."""
    event_name = evidence.get("event_name", "")
    policy_arn = evidence.get("policy_arn", "")
    target_user = evidence.get("target_user", "")
    target_role = evidence.get("target_role", "")
    access_key_id = evidence.get("access_key_id", "")

    if event_name == "AttachUserPolicy" and target_user and policy_arn:
        return f"DetachUserPolicy(UserName={target_user}, PolicyArn={policy_arn})"
    if event_name == "AttachRolePolicy" and target_role and policy_arn:
        return f"DetachRolePolicy(RoleName={target_role}, PolicyArn={policy_arn})"
    if event_name == "CreateAccessKey" and target_user and access_key_id:
        return f"UpdateAccessKey(UserName={target_user}, AccessKeyId={access_key_id}, Status=Inactive)"
    return None


@activity.defn(name="revoke_iam_privilege")
async def revoke_iam_privilege(events: list[SecurityEvent], dry_run: bool = False) -> ExecutionResult:
    """
    IAM 권한상승/지속성 확보 대응 — Incident에 묶인 이벤트 전부를 각각 회수한다(부여된
    관리형 정책 detach + 발급된 AccessKey 비활성화 등). 단일 이벤트 경로(계정 탈취 그룹이
    아닌 기존 AttachUserPolicy 단독 트리거)는 workflow.py가 원소 1개짜리 리스트로 감싸
    넘긴다 — 이 함수 입장에선 항상 리스트.
    실제 IAM 호출은 VPC 밖 Lambda(financial-secops-iam-responder)가 대신 한다 — ops VPC는
    IGW/NAT가 없고 IAM은 ap-northeast-2에 PrivateLink가 없어(us-east-1 전용) orchestrator가
    직접 호출 불가. Lambda는 이벤트 하나만 받는 구조라(핸들러는 안 건드림) 이벤트 수만큼
    순차 invoke한다.
      - dry_run=True (1단계 검증 호출): 이벤트마다 Lambda를 부르지 않고 '무엇을 할지'만
        번호 매겨 모은다 — 실제 IAM을 건드리는 경로 자체를 2차 승인 이후로 물리적으로 분리.
      - dry_run=False (2단계 실apply 호출): 이벤트마다 _invoke_iam_responder_lambda 호출,
        결과를 번호 매겨 모은다.
      - ISOLATION_DRY_RUN=true(apply_isolation과 공유하는 안전 스위치)면 dry_run 인자와
        무관하게 항상 canned dry-run(미적용, Lambda 호출 없음).
    지원 대상 외(PutUserPolicy 등 인라인 정책, AttachGroupPolicy, evidence 불충분) 이벤트는
    그 항목만 '미지원'으로 기록하고 success=False로 반영 — 재시도로 해결될 문제가 아니라
    raise는 안 함(추측으로 잘못된 API를 부르지 않는다는 원칙은 그대로).
    반대로 Lambda invoke 자체가 실패한 이벤트가 하나라도 있으면 raise한다 — Temporal이
    "성공"으로 착각해 재시도 없이 넘어가지 않도록(module docstring의 "ThrottlingException 등
    → 그냥 raise" 원칙과 동일). detach_user_policy/detach_role_policy는 이미 detach된
    정책을 다시 호출해도 에러 없이 통과하고(AWS IAM 문서 기준 일반 지식, 이 환경에서 실측은
    못 함), update_access_key(Status=Inactive)는 이미 Inactive인 키에 다시 호출해도 상태만
    재설정할 뿐이라 — 재시도로 전체 이벤트를 다시 돌려도 이미 성공한 항목이 다시 깨지지 않는다.
    """
    from .detection import extract_evidence

    force_dry_run = os.getenv("ISOLATION_DRY_RUN", "").lower() == "true"

    action_lines: list[str] = []
    any_unsupported = False
    any_execution_failed = False

    for idx, target_event in enumerate(events, start=1):
        evidence = extract_evidence(target_event)
        description = _describe_iam_action(evidence)

        if description is None:
            action_lines.append(
                f"{idx}. 미지원 (event_name={evidence.get('event_name', '')}) "
                f"— 자동 조치 없음, 수동 확인 필요"
            )
            any_unsupported = True
            continue

        if force_dry_run or dry_run:
            action_lines.append(f"{idx}. [DRY-RUN] {description} — 실제 미적용")
            continue

        try:
            outcome = await asyncio.to_thread(_invoke_iam_responder_lambda, evidence)
            action_lines.append(f"{idx}. {outcome}")
        except Exception as exc:  # noqa: BLE001 — 결과에 남기고 전체를 실패 처리해 재시도 유도
            action_lines.append(f"{idx}. 실패: {exc}")
            any_execution_failed = True

    action_taken = "\n".join(action_lines)

    if any_execution_failed:
        raise RuntimeError(action_taken)

    return ExecutionResult(
        workflow_id=events[0].workflow_id,
        success=not any_unsupported,
        action_taken=action_taken,
        output=action_taken,
    )


# =====================================================================
# 계정 탈취 lookback — target_user_arn 기준 과거 1시간 siem.cloudtrail(Athena) 조회
# =====================================================================
def _partition_days(start: datetime, end: datetime) -> list[tuple[str, str, str]]:
    """[start, end] 사이 걸쳐진 (year, month, day) 파티션 값 목록(UTC, inclusive).
    1시간 lookback 창이 자정을 넘으면 2개가 나온다."""
    days = []
    current = start.date()
    last = end.date()
    while current <= last:
        days.append((f"{current.year:04d}", f"{current.month:02d}", f"{current.day:02d}"))
        current += timedelta(days=1)
    return days


def _build_lookback_query(target_user_arn: str, trigger_time: datetime) -> tuple[str, datetime, datetime]:
    """target_user_arn 기준 과거 1시간 siem.cloudtrail 쿼리 문자열 + 조회 창(UTC) 반환."""
    window_start = trigger_time - timedelta(hours=1)
    window_end = trigger_time
    partitions = _partition_days(window_start, window_end)
    partition_clause = " OR ".join(
        f"(year='{y}' AND month='{m}' AND day='{d}')" for y, m, d in partitions
    )
    # requestParameters.userName은 ARN이 아니라 이름만 담김 — ARN 마지막 세그먼트로 매칭
    target_username = target_user_arn.rsplit("/", 1)[-1].replace("'", "''")
    target_user_arn_escaped = target_user_arn.replace("'", "''")
    start_iso = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")

    query = f"""
    SELECT
      eventid,
      eventtime,
      eventname,
      eventsource,
      useridentity.arn AS user_arn,
      sourceipaddress,
      awsregion,
      requestparameters,
      responseelements
    FROM siem.cloudtrail
    WHERE region = 'us-east-1'
      AND ({partition_clause})
      AND eventtime >= '{start_iso}'
      AND eventtime <= '{end_iso}'
      AND eventname IN ('AttachUserPolicy', 'PutUserPolicy', 'CreateAccessKey')
      AND (
        json_extract_scalar(requestparameters, '$.userName') = '{target_username}'
        OR useridentity.arn = '{target_user_arn_escaped}'
      )
    ORDER BY eventtime ASC
    """
    return query, window_start, window_end


def _query_siem_cloudtrail(target_user_arn: str, trigger_time: datetime) -> list[dict]:
    """실제 Athena 쿼리 실행(동기 boto3, asyncio.to_thread로 오프로드해 호출).
    WorkGroup을 명시(FinOps의 query_cur_via_athena는 이게 없어서 primary로 새 — 그 버그
    반복 금지, siem 워크그룹의 스캔 한도/암호화 강제를 실제로 적용받기 위해 필수).
    에러를 삼키지 않고 그대로 raise — 호출자(lookback_user_events)가 lookback_failed로 표시."""
    import time

    import boto3

    query, _, _ = _build_lookback_query(target_user_arn, trigger_time)
    region = os.getenv("AWS_REGION", "ap-northeast-2")
    database = os.getenv("SIEM_ATHENA_DATABASE", "siem")
    workgroup = os.getenv("SIEM_ATHENA_WORKGROUP", "siem")
    timeout_seconds = int(os.getenv("SIEM_ATHENA_TIMEOUT_SECONDS", "30"))

    athena = boto3.client("athena", region_name=region)
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database},
        WorkGroup=workgroup,
    )
    execution_id = response["QueryExecutionId"]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(2)
        status = athena.get_query_execution(QueryExecutionId=execution_id)
        state = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena lookback 쿼리 {state}: {reason}")
    else:
        raise TimeoutError(f"Athena lookback 쿼리 타임아웃({timeout_seconds}s)")

    rows: list[dict] = []
    columns: list[str] | None = None
    next_token = None
    while True:
        kwargs = {"QueryExecutionId": execution_id}
        if next_token:
            kwargs["NextToken"] = next_token
        results = athena.get_query_results(**kwargs)
        result_rows = results.get("ResultSet", {}).get("Rows", [])
        start_idx = 0
        if columns is None:
            if not result_rows:
                break
            columns = [item.get("VarCharValue", "") for item in result_rows[0]["Data"]]
            start_idx = 1
        for raw_row in result_rows[start_idx:]:
            values = [item.get("VarCharValue", "") for item in raw_row["Data"]]
            rows.append(dict(zip(columns, values)))
        next_token = results.get("NextToken")
        if not next_token:
            break
    return rows


def _has_related_event(rows: list[dict]) -> bool:
    """트리거(CreateAccessKey) 자신 말고 실제로 상관분석할 이벤트가 있는지.
    적재 지연으로 트리거 자신의 레코드만 뒤늦게 siem.cloudtrail에 잡힌 경우는
    '관련 이벤트 찾음'으로 치지 않는다 — 그래야 재조회 루프가 의미 있게 동작한다."""
    return any(row.get("eventname", "") != "CreateAccessKey" for row in rows)


@activity.defn(name="lookback_user_events")
async def lookback_user_events(
    target_user_arn: str, trigger_time: datetime, cluster_name: str,
) -> list[SecurityEvent]:
    """
    계정 탈취 lookback — target_user_arn 기준 과거 1시간 siem.cloudtrail(us-east-1)을
    Athena로 조회해 관련 이벤트(Admin 정책부여/AccessKey 생성)를 SecurityEvent 리스트로 반환.
    실패 시 빈 리스트로 조용히 넘기지 않고 예외를 그대로 전파한다 — 호출자(workflow.py)가
    IncidentGroup.lookback_failed=True로 표시하고 audit에 남긴다(Sonnet이 불완전 정보로
    판단하는 것을 방지 — FinOps의 blanket except-Exception-return-None 패턴 반복 금지).

    CloudTrail → S3 → Athena 적재 지연 대응: 트리거(CreateAccessKey) 발생 수십 초 뒤에
    lookback을 돌리면 그 직전 AttachUserPolicy 등이 아직 siem.cloudtrail에 반영 안 될 수
    있다(실측: 41초 후에도 미반영, 그 이후엔 조회됨). 트리거 말고는 아무것도 안 잡히면
    짧은 간격으로 재조회해 적재를 기다린다 — 그래도 안 잡히면 단일 이벤트로 그냥 진행
    (지금과 동일하게 Sonnet이 단일 이벤트로 판정).
    """
    from .detection import parse_eventbridge, to_security_event

    retry_max = int(os.getenv("SIEM_LOOKBACK_RETRY_MAX", "5"))
    retry_interval_seconds = int(os.getenv("SIEM_LOOKBACK_RETRY_INTERVAL_SECONDS", "15"))

    activity.heartbeat("lookback_user_events: querying siem.cloudtrail")
    rows = await asyncio.to_thread(_query_siem_cloudtrail, target_user_arn, trigger_time)

    attempt = 0
    while attempt < retry_max and not _has_related_event(rows):
        attempt += 1
        activity.logger.info(
            "lookback: target=%s 트리거 외 관련 이벤트 없음 — 적재 지연 대기 재조회 %d/%d (%ds 간격)",
            target_user_arn, attempt, retry_max, retry_interval_seconds,
        )
        activity.heartbeat(f"lookback_user_events: retry {attempt}/{retry_max} 대기")
        await asyncio.sleep(retry_interval_seconds)
        activity.heartbeat(f"lookback_user_events: retry {attempt}/{retry_max} 재조회")
        rows = await asyncio.to_thread(_query_siem_cloudtrail, target_user_arn, trigger_time)

    if attempt:
        activity.logger.info(
            "lookback: target=%s 재조회 종료 — %d회 시도 후 %s",
            target_user_arn, attempt,
            "관련 이벤트 발견" if _has_related_event(rows) else "트리거 단일 이벤트로 진행",
        )

    events: list[SecurityEvent] = []
    for row in rows:
        try:
            request_params = json.loads(row.get("requestparameters") or "{}")
        except json.JSONDecodeError:
            request_params = {}
        try:
            response_elements = json.loads(row.get("responseelements") or "{}")
        except json.JSONDecodeError:
            response_elements = {}
        synthetic_message = {
            "detail-type": "AWS API Call via CloudTrail",
            "detail": {
                "eventID": row.get("eventid", ""),
                "eventName": row.get("eventname", ""),
                "eventSource": row.get("eventsource", ""),
                "awsRegion": row.get("awsregion", ""),
                "sourceIPAddress": row.get("sourceipaddress", "0.0.0.0"),
                "userIdentity": {"arn": row.get("user_arn", "")},
                "requestParameters": request_params,
                "responseElements": response_elements,
                # Sonnet 인과판정용 원본 발생 시각 — Athena에서 이미 조회해온 값 그대로.
                "eventTime": row.get("eventtime", ""),
            },
        }
        parsed = parse_eventbridge(synthetic_message)
        events.append(to_security_event(parsed, cluster_name))
    activity.logger.info(
        "lookback: target=%s window=1h rows=%d", target_user_arn, len(events),
    )
    return events


# =====================================================================
# 침투 시나리오 lookback — Loki에서 최근 DROPPED(POLICY_DENIED) Hubble flow 조회
# 계정 탈취의 lookback_user_events(Athena)와 같은 자리. 조회(LogQL)는 단순하게,
# 분류/집계는 전부 여기(Python)서 한다 — 상관 윈도우 위치를 코드 쪽으로 정한 설계 그대로.
# =====================================================================
LOKI_URL = os.getenv("LOKI_URL", "").rstrip("/")
# 포트 개수 임계치 — 10은 시작값(튜닝 대상). env로 조정 가능하게.
PORT_SCAN_THRESHOLD = int(os.getenv("SECOPS_PORT_SCAN_THRESHOLD", "10"))
# 시간 하위창(초) — 같은 워크로드가 10분 lookback 창 안에서 "포트스캔(다수 포트, 짧은
# 버스트) → 측면이동(소수 포트, 나중에 targeted 접속)"을 순서대로 했을 때 이 둘을 서로
# 다른 개별판정으로 분리하기 위함. (워크로드, 카테고리) 하나로만 묶으면 전체 10분을 합산한
# distinct port 수 하나로만 port_scan/lateral_movement가 갈려 둘이 동시에 못 나온다 —
# 사슬 자체가 성립 안 됨. 120초는 시작값(튜닝 대상, PORT_SCAN_THRESHOLD와 같이 조정).
NETWORK_SUBWINDOW_SECONDS = int(os.getenv("SECOPS_NETWORK_SUBWINDOW_SECONDS", "120"))
# 네트워크 Rule Filter 제외 대상(하드코딩 대신 설정) — LogQL이 이미 좁혀오지만
# 그 필터를 우회한 레코드가 섞여 들어와도 여기서 다시 걸러낸다(IAM Rule Filter와 동일 이유).
_NETWORK_RULE_FILTER_EXCLUDED_SOURCES = {
    s.strip() for s in os.getenv("SECOPS_NETWORK_EXCLUDED_SOURCES", "observability-grafana").split(",")
    if s.strip()
}


def _network_rule_filter_skip(flow: dict) -> bool:
    """순수 판정(I/O 없음) — IAM의 _rule_filter_skip(workflow.py)과 대응되는 네트워크판.
    POLICY_DENIED가 아닌 drop(기술적 사유)이거나, 알려진 노이즈 소스(observability-grafana
    등, env로 설정)면 판정에서 제외한다."""
    if flow.get("drop_reason_desc", "") != "POLICY_DENIED":
        return True
    if flow.get("source_pod", "") in _NETWORK_RULE_FILTER_EXCLUDED_SOURCES:
        return True
    return False


def _parse_hubble_time(raw: str, fallback: datetime) -> datetime:
    """Hubble flow의 time 필드(RFC3339, 나노초 정밀도 가능) 파싱. fromisoformat은
    마이크로초(6자리)까지만 받아 나노초면 실패할 수 있어, 그 경우 6자리로 절삭해 재시도.
    그래도 실패하면 fallback(호출자가 안전하게 처리) — Sonnet 인과판정용 실제 발생
    시각이라 workflow.py의 _parse_trigger_time과 동일한 이유로 신경 써서 파싱한다."""
    text = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        pass
    truncated = re.sub(r"(\.\d{6})\d+(?=[+-]\d{2}:\d{2}$)", r"\1", text)
    try:
        return datetime.fromisoformat(truncated)
    except (ValueError, TypeError):
        return fallback


def _query_loki_dropped_flows(window_start: datetime, window_end: datetime) -> list[str]:
    """Loki query_range 호출 — monitoring/observability-indexer/main.py:35-49의 requests
    기반 패턴 그대로(query/start/end 나노초/limit/direction=backward). LogQL 자체는
    cilium-agent(kube-system) 로그에서 POLICY_DENIED 줄만, observability-grafana 소스는
    제외하고 가져온다 — 상세 분류는 이 함수가 아니라 호출자(파이썬)가 한다."""
    import requests

    if not LOKI_URL:
        raise RuntimeError("LOKI_URL 미설정 — 침투 시나리오 lookback 불가")

    query = (
        '{namespace="kube-system", pod=~"cilium-.*"} '
        '|= "POLICY_DENIED" != "observability-grafana"'
    )
    resp = requests.get(
        f"{LOKI_URL}/loki/api/v1/query_range",
        params={
            "query": query,
            "start": int(window_start.timestamp() * 1_000_000_000),
            "end": int(window_end.timestamp() * 1_000_000_000),
            "limit": 5000,
            "direction": "backward",
        },
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    return [
        line
        for stream in payload.get("data", {}).get("result", [])
        for _ts_ns, line in stream.get("values", [])
    ]


@activity.defn(name="lookback_network_flows")
async def lookback_network_flows(
    cluster_name: str, window_start: datetime, window_end: datetime,
) -> list[SecurityEvent]:
    """
    침투 시나리오 lookback — Loki에서 최근 DROPPED(POLICY_DENIED) flow를 조회해 같은
    소스 워크로드(workload_name, 없으면 source_pod) + 목적지 카테고리(detection.py의
    classify_destination_category) + 시간 하위창(NETWORK_SUBWINDOW_SECONDS) 기준으로
    묶고, "internal" 그룹은 distinct destination_port 수로 port_scan/lateral_movement를,
    "external" 그룹은 abnormal_outbound로 분류한다. 시간 하위창을 두는 이유: 카테고리로만
    묶으면 10분 전체의 distinct port 합산 하나로만 갈려 포트스캔(초반 버스트)과 측면이동
    (후반 targeted 접속)이 동시에 못 나온다 — "포트스캔→측면이동→outbound" 3단 사슬 자체가
    성립하려면 이 셋이 서로 다른 개별판정으로 나와야 한다. 그룹 하나당 SecurityEvent 하나만
    만든다 — 레코드 하나당 워크로드/LLM 호출을 만들면 포트스캔 하나가 레코드 수백~수만
    건이라 폭증하기 때문(개별 레코드 전부가 아니라 그룹 단위가 "개별 판정").

    워크로드 건너가는 사슬(A→B): internal 레코드의 목적지가 다른(식별된) 워크로드면 그
    사이에 edge를 긋고, union-find로 서로 이어진 워크로드를 하나의 chain_id로 묶는다.
    (워크로드, 카테고리, 하위창) 그룹은 여전히 워크로드별 개별판정 단위로 유지하되(격리
    시 각자의 isolation_labels가 필요하므로), chain_id를 evidence에 심어 workflow.py가
    "같은 침투 사슬"로 재조립할 수 있게 한다.
    """
    from .detection import (
        EVIDENCE_SEP,
        classify_destination_category,
        parse_hubble_flow,
        parse_isolation_labels,
    )

    activity.heartbeat("lookback_network_flows: querying loki")
    raw_lines = await asyncio.to_thread(_query_loki_dropped_flows, window_start, window_end)

    parsed_records = []
    for line in raw_lines:
        try:
            flow = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        record = parse_hubble_flow(flow)
        if record is None or _network_rule_filter_skip(record):
            continue
        parsed_records.append(record)

    # 워크로드 간 사슬 연결 — union-find. internal 레코드의 목적지 워크로드가 식별되면
    # (parse_hubble_flow의 destination_workload_name) 소스↔목적지를 같은 집합으로 묶는다.
    parent: dict[str, str] = {}

    def _find(w: str) -> str:
        parent.setdefault(w, w)
        while parent[w] != w:
            parent[w] = parent[parent[w]]
            w = parent[w]
        return w

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    for record in parsed_records:
        src = record["workload_name"] or record["source_pod"]
        _find(src)  # 아직 edge가 없는 워크로드도 union-find에 등록만 해둠
        if record["destination_workload_name"]:
            category = classify_destination_category(record["destination_labels"])
            if category == "internal":
                _union(src, record["destination_workload_name"])

    # (워크로드, 목적지 카테고리, 시간 하위창)으로 그룹화. 카테고리만으로 묶으면 10분
    # 전체를 합산한 distinct port 수 하나로 port_scan/lateral_movement 중 하나만 나와
    # "포트스캔(다수 포트, 초반 버스트) → 측면이동(소수 포트, 나중에 targeted 접속)"
    # 두 단계가 절대 동시에 안 나온다(사슬 자체가 성립 불가) — 시간 하위창으로 더
    # 쪼개야 초반 버스트와 후반 targeted 접속이 서로 다른 개별판정으로 분리된다.
    groups: dict[tuple[str, str, int], list[dict]] = {}
    for record in parsed_records:
        category = classify_destination_category(record["destination_labels"])
        if category is None:
            continue  # 클러스터 안/밖 어느 쪽도 아닌(기타 reserved 식별자 등) 판정 제외
        record_time = _parse_hubble_time(record["time"], window_end)
        subwindow = int((record_time - window_start).total_seconds() // NETWORK_SUBWINDOW_SECONDS)
        key = (record["workload_name"] or record["source_pod"], category, subwindow)
        groups.setdefault(key, []).append(record)

    events: list[SecurityEvent] = []
    for (workload_key, category, _subwindow), records in groups.items():
        distinct_ports = sorted({r["destination_port"] for r in records})
        latest = max(records, key=lambda r: r.get("time", ""))
        latest_time = _parse_hubble_time(latest["time"], window_end)
        if category == "external":
            threat_type = "abnormal_outbound"
        else:
            threat_type = "port_scan" if len(distinct_ports) >= PORT_SCAN_THRESHOLD else "lateral_movement"

        isolation_labels = parse_isolation_labels(latest["source_labels"])
        evidence = {
            "distinct_destination_ports": distinct_ports,
            "flow_count": len(records),
            "drop_reason_desc": latest["drop_reason_desc"],
            # dedup_events(detection.py)가 cloudtrail_event_id 없는 이벤트는 raw_log
            # 전체로 dedup한다 — 같은 워크로드가 서로 다른 하위창에서 우연히 동일한 포트
            # 집합/건수를 만들면 raw_log가 같아져 잘못 dedup될 수 있어, 실제 발생 시각을
            # 넣어 하위창마다 raw_log가 확실히 달라지게 한다.
            "detected_at": latest_time.isoformat(),
            # workflow.py가 이 값으로 워크로드를 건너가는 사슬을 재조립한다(by_workload가
            # 아니라 by_chain으로 묶음). 정보 없음 워크로드는 자기 자신만의 chain_id를 가짐.
            "chain_id": _find(workload_key),
            "destination_workload": latest["destination_workload_name"],
            "destination_namespace": latest["destination_namespace"],
        }
        raw_log = (
            f"[hubble] {workload_key} — DROPPED flow {len(records)}건, "
            f"목적지 포트 {len(distinct_ports)}개 (threat_type={threat_type})"
            f"{EVIDENCE_SEP}{json.dumps(evidence, ensure_ascii=False)}"
        )
        events.append(SecurityEvent(
            # Sonnet 인과판정(_describe_intrusion_events)이 시간순 정렬로 사슬을 판단하므로
            # activity 실행 시각(기본값 utc_now)이 아니라 실제 flow 발생 시각을 명시해야 한다
            # — 안 그러면 한 lookback 호출로 만들어진 이벤트들이 전부 같은 시각으로 찍혀
            # 시간순 판단 자체가 무의미해진다.
            detected_at=latest_time,
            cluster_name=cluster_name,
            namespace=latest["namespace"],
            source_pod=latest["source_pod"],
            workload_name=latest["workload_name"] or workload_key,
            workload_kind=latest["workload_kind"],
            isolation_labels=isolation_labels,
            source_ip=latest["source_ip"],
            destination_ip=latest["destination_ip"],
            destination_port=latest["destination_port"] or 1,
            protocol=latest["protocol"],
            direction="outbound",
            threat_type=threat_type,
            raw_log=raw_log,
            confidence=0.6,
            severity="medium",
            event_source="hubble",
        ))

    activity.logger.info(
        "lookback_network_flows: window=%s~%s raw=%d groups=%d events=%d chains=%d",
        window_start, window_end, len(raw_lines), len(groups), len(events),
        len({_find(w) for w in parent}),
    )
    return events


# =====================================================================
# Sonnet 인과판정 — 시간순 이벤트만 보고 계정 탈취/침투 여부 + Attack Summary
# 시나리오 공용(IncidentGroup.scenario) — 계정 탈취는 IAM 이벤트, 침투는 Cilium
# DROPPED flow 이벤트라 프롬프트·이벤트 서술 방식이 서로 달라 여기서 분기한다.
# =====================================================================
def _describe_account_takeover_events(incident_group: IncidentGroup) -> tuple[str, str]:
    from .detection import extract_evidence

    lines = []
    for i, event in enumerate(incident_group.events, start=1):
        evidence = extract_evidence(event)
        # detected_at은 파싱 처리 시각이라 이벤트 간 실제 간격을 안 보여줌 —
        # evidence["event_time"](원본 CloudTrail eventTime)을 우선 쓰고, 없으면 폴백.
        event_time = evidence.get("event_time") or event.detected_at.isoformat()
        lines.append(
            f"{i}. {event_time} event_name={evidence.get('event_name', '')} "
            f"정책={evidence.get('policy_arn', '')} 행위자={evidence.get('user_arn', '')}"
        )
    user_text = (
        f"[대상 IAM User]\n{incident_group.correlation_key}\n\n"
        f"[시간순 이벤트 목록 ({len(incident_group.events)}건)]\n" + "\n".join(lines)
    )
    system_prompt = (
        "너는 클라우드 계정 탈취 여부를 판단하는 보안 분석가다. 아래 IAM 이벤트들을 시간순으로만 "
        "보고, 이 사건이 계정 탈취(권한 상승 후 지속성 확보)인지 판단해라. 사건 요약(Attack Summary)도 "
        "작성해라. 근거에 없는 사실을 지어내지 마라. 반드시 아래 JSON만 출력해라.\n"
        '{"is_threat_confirmed": bool, "confidence": float, "causal_summary": string}'
    )
    return system_prompt, user_text


def _describe_intrusion_events(incident_group: IncidentGroup) -> tuple[str, str]:
    """워크로드 건너가는 사슬(A→B)일 수 있어 각 줄에 소스 워크로드를 명시하고, 목적지도
    IP 대신 (알려진 경우) 목적지 워크로드 이름으로 보여준다 — Sonnet이 "이 레코드의 목적지가
    다른 레코드의 소스와 같은 워크로드"임을 직접 읽어내 사슬을 재구성할 수 있게."""
    from .detection import extract_evidence

    lines = []
    for i, event in enumerate(incident_group.events, start=1):
        ev = extract_evidence(event)
        if ev.get("destination_workload"):
            destination_label = f"{ev['destination_workload']}({ev.get('destination_namespace', '')})"
        else:
            destination_label = str(event.destination_ip)
        lines.append(
            f"{i}. {event.detected_at.isoformat()} threat_type={event.threat_type} "
            f"{event.workload_name or event.source_pod}({event.namespace}) -> "
            f"{destination_label}:{event.destination_port}/{event.protocol} "
            f"direction={event.direction}"
        )
    user_text = (
        f"[관련 워크로드]\n{incident_group.correlation_key}\n\n"
        f"[시간순 이벤트 목록 ({len(incident_group.events)}건)]\n" + "\n".join(lines)
    )
    system_prompt = (
        "너는 클라우드 네트워크 침해 여부를 판단하는 보안 분석가다. 아래는 하나 이상의 "
        "워크로드에 걸쳐 시간순으로 발생한 Cilium 차단(DROPPED) 이벤트들이다(포트스캔/"
        "측면이동/비정상 외부 outbound 후보) — 한 레코드의 목적지가 다른 레코드의 소스와 "
        "같은 워크로드면 워크로드를 건너가는 사슬(예: A가 스캔한 뒤 B로 이동, B가 외부로 "
        "유출)일 수 있다. 이 사건이 포트스캔→측면이동→외부유출로 이어지는 다단계 침투인지 "
        "판단해라. 사건 요약(Attack Summary)도 작성해라. 근거에 없는 사실을 지어내지 마라. "
        "반드시 아래 JSON만 출력해라.\n"
        '{"is_threat_confirmed": bool, "confidence": float, "causal_summary": string}'
    )
    return system_prompt, user_text


def _correlate_with_bedrock(incident_group: IncidentGroup) -> dict:
    """(A)방식 — 개별 이벤트의 상세 맥락(정책 위험도 재판단 등) 없이, 시간순 이벤트
    목록만 주고 인과관계 판단을 맡긴다."""
    from botocore.exceptions import ClientError
    from shared.bedrock import get_bedrock_client

    client = get_bedrock_client()
    if incident_group.scenario == "account_takeover":
        system_prompt, user_text = _describe_account_takeover_events(incident_group)
    else:
        system_prompt, user_text = _describe_intrusion_events(incident_group)
    try:
        resp = client.converse(
            modelId=BEDROCK_MODEL_SONNET,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0},
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ValidationException":
            raise ApplicationError(
                f"Bedrock Sonnet 인과판정 ValidationException: {e}", non_retryable=True
            ) from e
        raise
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    data = _parse_llm_json(text)
    return {
        "is_threat_confirmed": bool(data.get("is_threat_confirmed", False)),
        "confidence": float(data.get("confidence", 0.5)),
        "causal_summary": str(data.get("causal_summary", "")),
    }


@activity.defn(name="correlate_incident")
async def correlate_incident(incident_group: IncidentGroup) -> IncidentGroup:
    """Sonnet 인과판정 1회 — IncidentGroup에 causal_summary/is_threat_confirmed/
    correlation_confidence를 채워 반환. USE_REAL_BEDROCK=false면 결정적 stub."""
    if not USE_REAL_BEDROCK:
        is_confirmed = len(incident_group.events) >= 2
        label = "계정 탈취 의심" if incident_group.scenario == "account_takeover" else "다단계 침투 의심"
        return incident_group.model_copy(update={
            "is_threat_confirmed": is_confirmed,
            "correlation_confidence": 0.8 if is_confirmed else 0.3,
            "causal_summary": (
                f"(stub) {incident_group.correlation_key} 대상 {len(incident_group.events)}건 "
                f"이벤트 — {label if is_confirmed else '단발성 이벤트'}"
            ),
        })
    result = await asyncio.to_thread(_correlate_with_bedrock, incident_group)
    return incident_group.model_copy(update={
        "is_threat_confirmed": result["is_threat_confirmed"],
        "correlation_confidence": result["confidence"],
        "causal_summary": result["causal_summary"],
    })


@activity.defn(name="generate_compliance_report")
async def generate_compliance_report(input: GenerateComplianceReportInput) -> ComplianceReport:
    """event + mapping + 실행결과 → 규제 대응 보고서."""
    e, m, r = input.event, input.mapping, input.result
    return ComplianceReport(
        workflow_id=e.workflow_id,
        severity=m.severity,
        violated_regulations=m.violated_regulations,
        blast_radius_safe=m.blast_radius_safe,
        blast_radius_detail=m.blast_radius_detail,
        threat_summary=f"{e.threat_type} from {e.source_pod}",
        action_taken=r.action_taken,
        isolation_applied=r.success,
        confidence=m.confidence,
        evidence=m.evidence,
    )


@activity.defn(name="record_compliance_report")
async def record_compliance_report(report: ComplianceReport) -> None:
    """ComplianceReport를 RDS에 저장 (record_audit_log와 동일 패턴)."""
    from shared.reports import save_compliance_report

    await save_compliance_report(report)
    activity.logger.info(
        "[report] %s | severity=%s | isolation=%s",
        report.workflow_id, report.severity, report.isolation_applied,
    )


def _draft_postmortem_with_bedrock(
    e: SecurityEvent, m: RegulationMapping, r: ExecutionResult
) -> dict:
    """Sev1/2 사후분석 초안 (Sonnet): root_cause / action_items / lessons_learned.
    generate_compliance_report와 달리 서술형 회고를 생성 — analyze와 동일 converse 패턴."""
    from botocore.exceptions import ClientError
    from shared.bedrock import get_bedrock_client

    client = get_bedrock_client()
    system_prompt = (
        "너는 금융 보안 사고 대응(Post-Mortem) 분석가다. 주어진 보안 이벤트/규제 매핑/대응 결과를 바탕으로 "
        "비난 없는(blameless) 사후분석 초안을 작성해라. 근거에 없는 사실을 지어내지 마라. "
        "반드시 아래 JSON 스키마만 출력해라.\n"
        '{"root_cause": string, "impact": string, "action_items": [string], "lessons_learned": string}'
    )
    user_text = (
        f"[보안 이벤트]\n{e.model_dump_json(indent=2)}\n\n"
        f"[규제 매핑]\n위반규정={m.violated_regulations}\n설명={m.violation_description}\n"
        f"blast_radius_safe={m.blast_radius_safe} detail={m.blast_radius_detail}\n\n"
        f"[대응 결과]\n{r.action_taken} (success={r.success})"
    )
    try:
        resp = client.converse(
            modelId=BEDROCK_MODEL,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.2},
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ValidationException":
            raise ApplicationError(
                f"Bedrock postmortem ValidationException: {exc}", non_retryable=True
            ) from exc
        raise
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    data = _parse_llm_json(text)
    return {
        "root_cause": str(data.get("root_cause", "")),
        "impact": str(data.get("impact", "")),
        "action_items": [str(x) for x in data.get("action_items", [])],
        "lessons_learned": str(data.get("lessons_learned", "")),
    }


def _draft_postmortem_stub(
    e: SecurityEvent, m: RegulationMapping, r: ExecutionResult
) -> dict:
    """USE_REAL_BEDROCK=false일 때의 결정적 초안 — 이벤트/매핑에서 직접 구성."""
    return {
        "root_cause": (
            f"{e.source_pod}({e.namespace})에서 {e.threat_type} 발생 — "
            f"{m.violation_description}"
        ),
        "impact": (
            f"영향 범위: {'단일 pod 흡수 가능(안전)' if m.blast_radius_safe else '광범위(위험)'} — "
            f"{m.blast_radius_detail or '상세 없음'}"
        ),
        "action_items": [
            f"{e.namespace}/{e.source_pod} 관련 접근통제 정책 재점검",
            "동일 threat_type 탐지 룰/알림 임계치 검토",
            "격리 자동화 및 blast radius 판정 기준 재검증",
        ],
        "lessons_learned": (
            f"위반 규정({', '.join(m.violated_regulations) or '해당 없음'})에 대한 대응은 "
            f"'{r.action_taken}'로 마무리됨. 탐지→승인→격리 파이프라인의 반응시간 개선 여지 점검 필요."
        ),
    }


@activity.defn(name="generate_postmortem_report")
async def generate_postmortem_report(input: GeneratePostMortemReportInput) -> PostMortemReport:
    """event + mapping + 실행결과 → Sev1/2 사후분석(Post-Mortem) 보고서.
    USE_REAL_BEDROCK=true면 Sonnet 초안, false면 결정적 stub."""
    e, m, r = input.event, input.mapping, input.result
    draft = _draft_postmortem_with_bedrock(e, m, r) if USE_REAL_BEDROCK else _draft_postmortem_stub(e, m, r)
    timeline = (
        f"{e.detected_at:%Y-%m-%d %H:%M:%SZ} 탐지: {e.threat_type} ({e.source_pod} → "
        f"{e.destination_ip}:{e.destination_port})\n"
        f"규제 매핑: severity={m.severity}, 위반={m.violated_regulations}\n"
        f"대응: {r.action_taken}"
    )
    return PostMortemReport(
        workflow_id=e.workflow_id,
        severity=m.severity,
        incident_summary=f"{e.threat_type} from {e.source_pod} ({e.namespace})",
        timeline=timeline,
        root_cause=draft["root_cause"],
        impact=draft["impact"],
        action_items=draft["action_items"],
        lessons_learned=draft["lessons_learned"],
        isolation_applied=r.success,
        evidence=m.evidence,
    )


@activity.defn(name="record_postmortem_report")
async def record_postmortem_report(report: PostMortemReport) -> None:
    """PostMortemReport를 RDS에 저장 (record_compliance_report와 동일 패턴)."""
    from shared.reports import save_postmortem_report

    await save_postmortem_report(report)
    activity.logger.info(
        "[postmortem] %s | severity=%s | action_items=%d",
        report.workflow_id, report.severity, len(report.action_items),
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


@activity.defn(name="send_action_result")
async def send_action_result(ticket: ApprovalTicket, message: str) -> None:
    """대응 실행 결과 Slack 통지(stub). 실제 구현은 slack-hitl bot.py."""
    activity.logger.info("Slack 결과 통지(stub): %s", message)
