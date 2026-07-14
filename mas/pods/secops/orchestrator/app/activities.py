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

    # 4) 위협 유형 가중 (port_scan/policy_violation은 단일 격리로 충분치 않을 수 있음)
    if event.threat_type in ("port_scan", "policy_violation"):
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

    네임스페이스 스코프(CiliumNetworkPolicy)로 생성해 대상 pod가 있는 ns에만 적용.
    """
    return f"""apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: isolate-{event.source_pod}
  namespace: {event.namespace}
  labels:
    app.kubernetes.io/managed-by: secops-mas
    secops.mas/isolation: "true"
spec:
  description: "SecOps 자동 격리 - {event.source_pod} ({event.threat_type})"
  endpointSelector:
    matchLabels:
      pod: {event.source_pod}
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
    return RegulationMapping(
        workflow_id=event.workflow_id,
        violated_regulations=analysis["violated_regulations"],
        violation_description=analysis["violation_description"],
        blast_radius_safe=safe,
        blast_radius_detail=detail,
        isolation_policy_yaml=build_isolation_policy(event),
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
    CiliumNetworkPolicy(mapping.isolation_policy_yaml)를 클러스터에 멱등 적용.
      - dry_run=True (1단계 검증 호출): k8s API 서버측 dry_run="All"로 검증만, 미반영
      - dry_run=False (2단계 실apply 호출): in-cluster 자격증명으로 실제 apply (create-or-replace)
      - 로컬/발표(클러스터 미연결) 또는 ISOLATION_DRY_RUN=true: dry_run 인자와 무관하게 항상
        canned dry-run(정책 검증만, 미적용) — 기존 안전망 그대로 유지
    상태 변경 Activity → heartbeat. 동기 k8s 호출은 스레드로 오프로드(이벤트 루프 비차단).
    """
    import yaml

    activity.heartbeat("apply_isolation: start")
    doc = yaml.safe_load(mapping.isolation_policy_yaml)
    name = doc.get("metadata", {}).get("name", "?")
    ns = doc.get("metadata", {}).get("namespace", "default")

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
            action_taken=f"[DRY-RUN] CiliumNetworkPolicy '{name}' (ns={ns}) 검증 완료 — 클러스터 미적용",
            output=mapping.isolation_policy_yaml,
        )

    if dry_run:
        activity.heartbeat("apply_isolation: server-side dry-run")
        await asyncio.to_thread(_apply_isolation_policy, doc, True)
        return ExecutionResult(
            workflow_id=mapping.workflow_id,
            success=True,
            action_taken=f"[DRY-RUN] CiliumNetworkPolicy '{name}' (ns={ns}) 서버 검증 완료 — 클러스터 미적용",
            output=mapping.isolation_policy_yaml,
        )

    activity.heartbeat("apply_isolation: applying")
    outcome = await asyncio.to_thread(_apply_isolation_policy, doc, False)
    return ExecutionResult(
        workflow_id=mapping.workflow_id,
        success=True,
        action_taken=f"CiliumNetworkPolicy '{name}' (ns={ns}) {outcome} — pod 격리 적용",
        output=f"{outcome}: {name} (ns={ns})",
    )


# IAM 대응이 실제로 지원하는 event_name → revoke API 종류. 아래 3종만 지원 —
# secops-role.tf에 부여된 권한(DetachUserPolicy/DetachRolePolicy/UpdateAccessKey)과
# 정확히 일치시켜, 권한 없는 API를 호출하는 코드 경로가 생기지 않도록 한다.
# PutUserPolicy/PutRolePolicy(인라인 정책, policy_arn 없음)와 AttachGroupPolicy는
# 미지원 — evidence가 부족하거나(정책 이름 없음) 대응 권한이 없어 조치 없이 보고만 함.
def _revoke_iam_privilege(evidence: dict) -> str:
    """실제 IAM detach/deactivate 호출 (동기 boto3). 반환: 사람이 읽는 결과 설명."""
    import boto3

    event_name = evidence.get("event_name", "")
    policy_arn = evidence.get("policy_arn", "")
    target_user = evidence.get("target_user", "")
    target_role = evidence.get("target_role", "")
    access_key_id = evidence.get("access_key_id", "")

    iam = boto3.client("iam")  # IAM은 글로벌 서비스 — region 불필요

    if event_name == "AttachUserPolicy" and target_user and policy_arn:
        iam.detach_user_policy(UserName=target_user, PolicyArn=policy_arn)
        return f"DetachUserPolicy 완료: UserName={target_user}, PolicyArn={policy_arn}"

    if event_name == "AttachRolePolicy" and target_role and policy_arn:
        iam.detach_role_policy(RoleName=target_role, PolicyArn=policy_arn)
        return f"DetachRolePolicy 완료: RoleName={target_role}, PolicyArn={policy_arn}"

    if event_name == "CreateAccessKey" and target_user and access_key_id:
        iam.update_access_key(UserName=target_user, AccessKeyId=access_key_id, Status="Inactive")
        return f"AccessKey 비활성화 완료: UserName={target_user}, AccessKeyId={access_key_id}"

    raise ValueError(
        f"IAM 대응 미지원 또는 evidence 불충분: event_name={event_name}, "
        f"target_user={target_user}, target_role={target_role}, "
        f"policy_arn={policy_arn}, access_key_id={access_key_id}"
    )


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
async def revoke_iam_privilege(event: SecurityEvent, dry_run: bool = False) -> ExecutionResult:
    """
    IAM 권한상승/지속성 확보 대응 — 부여된 관리형 정책 detach 또는 발급된 AccessKey 비활성화.
      - dry_run=True (1단계 검증 호출): 실제 IAM API 호출 없이 '무엇을 할지'만 반환
      - dry_run=False (2단계 실apply 호출): 실제 detach/update 실행
      - ISOLATION_DRY_RUN=true(apply_isolation과 공유하는 안전 스위치)면 dry_run 인자와
        무관하게 항상 canned dry-run(미적용)
    지원 대상 외(PutUserPolicy 등 인라인 정책, AttachGroupPolicy, evidence 불충분)는
    success=False로 '조치 없음' 보고 — 추측으로 잘못된 API를 부르지 않음.
    """
    from .detection import extract_evidence

    activity.heartbeat("revoke_iam_privilege: start")
    evidence = extract_evidence(event)
    description = _describe_iam_action(evidence)

    if description is None:
        return ExecutionResult(
            workflow_id=event.workflow_id,
            success=False,
            action_taken=(
                f"IAM 대응 미지원 또는 정보 부족 (event_name={evidence.get('event_name', '')}) "
                f"— 자동 조치 없음, 수동 확인 필요"
            ),
        )

    force_dry_run = os.getenv("ISOLATION_DRY_RUN", "").lower() == "true"
    if force_dry_run or dry_run:
        return ExecutionResult(
            workflow_id=event.workflow_id,
            success=True,
            action_taken=f"[DRY-RUN] {description} — 실제 미적용",
            output=description,
        )

    activity.heartbeat("revoke_iam_privilege: applying")
    outcome = await asyncio.to_thread(_revoke_iam_privilege, evidence)
    return ExecutionResult(
        workflow_id=event.workflow_id,
        success=True,
        action_taken=outcome,
        output=description,
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
# Sonnet 인과판정 — 시간순 이벤트만 보고 계정 탈취 여부 + Attack Summary
# =====================================================================
def _correlate_with_bedrock(incident_group: IncidentGroup) -> dict:
    """(A)방식 — 개별 이벤트의 상세 맥락(정책 위험도 재판단 등) 없이, 시간순 이벤트
    목록만 주고 인과관계 판단을 맡긴다."""
    from botocore.exceptions import ClientError
    from shared.bedrock import get_bedrock_client

    from .detection import extract_evidence

    client = get_bedrock_client()
    system_prompt = (
        "너는 클라우드 계정 탈취 여부를 판단하는 보안 분석가다. 아래 IAM 이벤트들을 시간순으로만 "
        "보고, 이 사건이 계정 탈취(권한 상승 후 지속성 확보)인지 판단해라. 사건 요약(Attack Summary)도 "
        "작성해라. 근거에 없는 사실을 지어내지 마라. 반드시 아래 JSON만 출력해라.\n"
        '{"is_account_takeover": bool, "confidence": float, "causal_summary": string}'
    )
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
        f"[대상 IAM User]\n{incident_group.target_user_arn}\n\n"
        f"[시간순 이벤트 목록 ({len(incident_group.events)}건)]\n" + "\n".join(lines)
    )
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
        "is_account_takeover": bool(data.get("is_account_takeover", False)),
        "confidence": float(data.get("confidence", 0.5)),
        "causal_summary": str(data.get("causal_summary", "")),
    }


@activity.defn(name="correlate_incident")
async def correlate_incident(incident_group: IncidentGroup) -> IncidentGroup:
    """Sonnet 인과판정 1회 — IncidentGroup에 causal_summary/is_account_takeover/
    correlation_confidence를 채워 반환. USE_REAL_BEDROCK=false면 결정적 stub."""
    if not USE_REAL_BEDROCK:
        is_takeover = len(incident_group.events) >= 2
        return incident_group.model_copy(update={
            "is_account_takeover": is_takeover,
            "correlation_confidence": 0.8 if is_takeover else 0.3,
            "causal_summary": (
                f"(stub) {incident_group.target_user_arn} 대상 {len(incident_group.events)}건 "
                f"이벤트 — {'계정 탈취 의심' if is_takeover else '단발성 이벤트'}"
            ),
        })
    result = await asyncio.to_thread(_correlate_with_bedrock, incident_group)
    return incident_group.model_copy(update={
        "is_account_takeover": result["is_account_takeover"],
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
