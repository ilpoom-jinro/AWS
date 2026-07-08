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
    """트리거 메시지가 있으면 파싱·보강, 없으면(run_demo/수동) 더미 이벤트 생성."""
    if input.trigger_message:
        from .detection import message_to_event
        from .telemetry import enrich_flow_logs
        event = message_to_event(input.trigger_message, input.cluster_name, enrich_flow_logs)
        if event is not None:
            activity.logger.info("threat parsed from trigger: workflow_id=%s source=%s",
                                 event.workflow_id, event.event_source)
            return event
        activity.logger.warning("trigger 파싱 실패 → 더미로 폴백")
    # 폴백/데모: 외부 유출 더미 이벤트
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
    activity.logger.info("threat detected (dummy): workflow_id=%s", event.workflow_id)
    return event


@activity.defn(name="map_regulation")
async def map_regulation(event: SecurityEvent) -> RegulationMapping:
    """RAG 규정 조회 + 2단계 Bedrock 판단(Nova→Sonnet) + Blast Radius + 격리 정책 생성."""
    chunks = retrieve_regulations(event)
    analysis = analyze_violation(event, chunks)
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


def _apply_authorization_policy(doc: dict) -> str:
    """Istio AuthorizationPolicy를 멱등 apply (create; 이미 있으면 replace). 반환 'created'|'replaced'."""
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    group, version = doc["apiVersion"].split("/", 1)   # security.istio.io, v1
    plural = "authorizationpolicies"
    ns = doc["metadata"].get("namespace") or "default"
    name = doc["metadata"]["name"]
    api = client.CustomObjectsApi()
    try:
        api.create_namespaced_custom_object(group, version, ns, plural, doc)
        return "created"
    except ApiException as exc:
        if exc.status != 409:            # 409=이미 존재 → replace로 멱등, 그 외는 전파(재시도)
            raise
        existing = api.get_namespaced_custom_object(group, version, ns, plural, name)
        doc["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
        api.replace_namespaced_custom_object(group, version, ns, plural, name, doc)
        return "replaced"


@activity.defn(name="apply_isolation")
async def apply_isolation(mapping: RegulationMapping) -> ExecutionResult:
    """
    Istio AuthorizationPolicy(mapping.isolation_policy_yaml)를 클러스터에 멱등 적용.
      - 배포 Pod: in-cluster 자격증명으로 실제 apply (create-or-replace)
      - 로컬/발표(클러스터 미연결) 또는 ISOLATION_DRY_RUN=true: dry-run (정책 검증만, 미적용)
    상태 변경 Activity → heartbeat. 동기 k8s 호출은 스레드로 오프로드(이벤트 루프 비차단).
    """
    import yaml

    activity.heartbeat("apply_isolation: start")
    doc = yaml.safe_load(mapping.isolation_policy_yaml)
    name = doc.get("metadata", {}).get("name", "?")
    ns = doc.get("metadata", {}).get("namespace", "default")

    dry_run = os.getenv("ISOLATION_DRY_RUN", "").lower() == "true"
    if not dry_run:
        from kubernetes.config.config_exception import ConfigException
        try:
            await asyncio.to_thread(_load_k8s_config)
        except ConfigException:
            # 클러스터 설정 없음(로컬/발표자 PC)만 dry-run. 그 외(패키지 미설치·네트워크 등)는 전파.
            dry_run = True

    if dry_run:
        return ExecutionResult(
            workflow_id=mapping.workflow_id,
            success=True,
            action_taken=f"[DRY-RUN] AuthorizationPolicy '{name}' (ns={ns}) 검증 완료 — 클러스터 미적용",
            output=mapping.isolation_policy_yaml,
        )

    activity.heartbeat("apply_isolation: applying")
    outcome = await asyncio.to_thread(_apply_authorization_policy, doc)
    return ExecutionResult(
        workflow_id=mapping.workflow_id,
        success=True,
        action_taken=f"Istio AuthorizationPolicy '{name}' (ns={ns}) {outcome} — pod 격리 적용",
        output=f"{outcome}: {name} (ns={ns})",
    )


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
