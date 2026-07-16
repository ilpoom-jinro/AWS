"""
SecOps 탐지 메시지 파싱 → SecurityEvent 변환 (+ 증적 결선)
=========================================================
봉근님 트리거(secops-trigger.tf)가 financial-secops-trigger SQS로 보내는 메시지를 파싱한다.
raw_message_delivery=true 라 SNS 봉투 없이 원본 JSON이 온다.

메시지 종류:
    1) CloudWatch Alarm JSON   — flow_logs / api_anomaly. 신호만(IP/포트 없음).
       → Flow Logs 재조회(telemetry.enrich_flow_logs)로 실제 REJECT 레코드 보강.
    2) EventBridge(CloudTrail) — iam_violation / network_change. 실제 Event ID 포함.
       → 증적(evidence)에 CloudTrail Event ID 결선 (3번).

증적 전달:
    SecurityEvent에는 evidence 필드가 없어(계약), 증적 JSON을 raw_log 끝에 실어 보낸다.
    map_regulation이 extract_evidence(event)로 꺼내 RegulationMapping.evidence에 병합.
"""

from __future__ import annotations

import ipaddress
import json

from contracts.models import SecurityEvent

# SecurityEvent엔 evidence 필드가 없어 raw_log에 증적을 실어 map_regulation까지 전달
EVIDENCE_SEP = " ||EVIDENCE|| "

_ALARM_METRIC = {
    "RejectCount": ("port_scan", "REJECT 버스트 (스캔/공격 급증 의심)"),
    "DbPortProbeCount": ("port_scan", "외부→DB포트 REJECT (포트 probe 의심)"),
    "AccessDeniedCount": ("policy_violation", "AccessDenied 급증"),
    "DeleteEventCount": ("policy_violation", "대량 Delete 시도"),
}


def _is_ip(s) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except (ValueError, TypeError):
        return False


def classify_message(body: str) -> str:
    """SQS body(JSON) → 'alarm' | 'eventbridge' | 'intrusion_trigger' | 'unknown'."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    if "AlarmName" in data or "Trigger" in data:
        return "alarm"
    if str(data.get("source", "")).startswith("aws.") or "detail-type" in data:
        return "eventbridge"
    if data.get("scenario") == "intrusion":
        return "intrusion_trigger"
    return "unknown"


def parse_alarm(data: dict) -> dict:
    """CloudWatch Alarm → 부분 필드 + needs_enrichment(Flow Logs 재조회 필요)."""
    trig = data.get("Trigger") or {}
    metric = trig.get("MetricName", "")
    threat, desc = _ALARM_METRIC.get(metric, ("policy_violation", "보안 알람"))
    vpc_hint = ""
    for token in (trig.get("Namespace", ""), data.get("AlarmName", "")):
        for part in str(token).replace("/", "-").split("-"):
            if part in ("vpc1", "vpc2"):
                vpc_hint = part
    return {
        "threat_type": threat,
        "event_source": "vpc_flow_log",
        "summary": data.get("AlarmDescription") or desc,
        "vpc_hint": vpc_hint,
        "metric_name": metric,
        "needs_enrichment": True,
        "evidence": {
            "alarm_name": data.get("AlarmName", ""),
            "metric_name": metric,
            "new_state_reason": data.get("NewStateReason", ""),
        },
    }


def parse_eventbridge(data: dict) -> dict:
    """EventBridge(CloudTrail) → 부분 필드 + 실 Event ID 증적."""
    detail = data.get("detail") or {}
    src_ip = detail.get("sourceIPAddress", "0.0.0.0")
    if not _is_ip(src_ip):
        src_ip = "0.0.0.0"
    request_params = detail.get("requestParameters") or {}
    # CreateAccessKey는 생성된 AccessKeyId가 요청이 아니라 응답(responseElements)에 실림.
    response_elements = detail.get("responseElements") or {}
    access_key_id = ((response_elements.get("accessKey") or {}).get("accessKeyId", ""))
    return {
        "threat_type": "policy_violation",
        "event_source": "cloudtrail",
        "source_ip": src_ip,
        "summary": f"{detail.get('eventName', 'API')} by {(detail.get('userIdentity') or {}).get('arn', 'unknown')}",
        "needs_enrichment": False,
        "evidence": {
            "cloudtrail_event_id": detail.get("eventID", ""),
            "event_name": detail.get("eventName", ""),
            "event_source": detail.get("eventSource", ""),
            "aws_region": detail.get("awsRegion", ""),
            "user_arn": (detail.get("userIdentity") or {}).get("arn", ""),
            "detail_type": data.get("detail-type", ""),
            # 계정 탈취 인과판정(Sonnet)이 이벤트 간 실제 시간 간격을 보려면 필요 —
            # SecurityEvent.detected_at은 파싱 처리 시각이라 원본 CloudTrail 발생
            # 시각과 다름(다른 시나리오 공용 필드라 안 건드림). 트리거/lookback 이벤트
            # 둘 다 이 함수를 거치므로 동일하게 채워짐.
            "event_time": detail.get("eventTime", ""),
            # Rule Filter(workflow.py)의 권한부여 위험도 판단용 — 계정 탈취 대응
            "policy_arn": request_params.get("policyArn", ""),
            "target_user": request_params.get("userName", ""),
            "target_role": request_params.get("roleName", ""),
            "target_group": request_params.get("groupName", ""),
            # revoke_iam_privilege(activities.py)의 CreateAccessKey 대응용
            "access_key_id": access_key_id,
        },
    }


def parse_intrusion_trigger(data: dict) -> dict:
    """침투 시나리오 수동 트리거 — 조회 조건 없음(설계 결정: 트리거는 사람이 버튼만
    누르고, 조회 범위는 "클러스터 전체·최근 10분"으로 고정). 이 파싱 결과엔 실제 Hubble
    데이터가 없다 — event_source="hubble"만 찍힌 seed SecurityEvent를 만들어
    workflow.py가 이를 보고 lookback_network_flows(Loki 조회)를 돌린다(계정 탈취의
    CreateAccessKey 트리거와 같은 역할, 실제 판정은 lookback 이후 개별 이벤트가 가짐)."""
    return {
        "threat_type": "policy_violation",  # placeholder — workflow.py가 lookback 후 대표 이벤트로 교체
        "event_source": "hubble",
        "summary": "침투 시나리오 수동 트리거 — Loki lookback 예정",
        "needs_enrichment": False,
        "evidence": {},
    }


def parse_message(body: str) -> dict | None:
    """SQS body → 파싱 결과 dict (kind 포함). 파싱 불가 시 None."""
    kind = classify_message(body)
    data = json.loads(body) if kind != "unknown" else None
    if kind == "alarm":
        return {"kind": kind, **parse_alarm(data)}
    if kind == "eventbridge":
        return {"kind": kind, **parse_eventbridge(data)}
    if kind == "intrusion_trigger":
        return {"kind": kind, **parse_intrusion_trigger(data)}
    return None


def to_security_event(parsed: dict, cluster_name: str, enrichment: dict | None = None) -> SecurityEvent:
    """파싱(+Flow Logs 보강)을 SecurityEvent로 조립. 증적은 raw_log 끝에 JSON으로 실음."""
    e = {**parsed, **(enrichment or {})}
    evidence = {**parsed.get("evidence", {}), **((enrichment or {}).get("evidence", {}))}

    raw_log = (e.get("summary", "") or "") + EVIDENCE_SEP + json.dumps(evidence, ensure_ascii=False)

    return SecurityEvent(
        cluster_name=cluster_name,
        namespace=e.get("namespace", "unknown"),
        source_pod=e.get("source_pod", "unknown"),
        source_ip=str(e.get("source_ip", "0.0.0.0")),
        destination_ip=str(e.get("destination_ip", "0.0.0.0")),
        destination_port=int(e.get("destination_port", 0)) or 1,
        protocol=e.get("protocol", "tcp"),
        direction=e.get("direction", "outbound"),
        threat_type=e.get("threat_type", "policy_violation"),
        raw_log=raw_log,
        confidence=float(e.get("confidence", 0.5)),
        severity=e.get("severity", "medium"),
        event_source=e.get("event_source", "stub"),
    )


def extract_evidence(event: SecurityEvent) -> dict:
    """raw_log 끝에 실린 증적 JSON을 복원. 없으면 {}."""
    if EVIDENCE_SEP not in event.raw_log:
        return {}
    try:
        return json.loads(event.raw_log.split(EVIDENCE_SEP, 1)[1])
    except (json.JSONDecodeError, IndexError):
        return {}


def message_to_event(body: str, cluster_name: str, enrich_flow_logs=None) -> SecurityEvent | None:
    """
    통합 진입점: SQS body → SecurityEvent. 파싱 불가 시 None.
    enrich_flow_logs: (parsed)->enrichment dict 콜백(telemetry 주입). 실패해도 신호 기반 진행.
    """
    parsed = parse_message(body)
    if parsed is None:
        return None
    enrichment = None
    if parsed.get("needs_enrichment") and enrich_flow_logs is not None:
        try:
            enrichment = enrich_flow_logs(parsed)
        except Exception:  # noqa: BLE001
            enrichment = None
    return to_security_event(parsed, cluster_name, enrichment)


# 워크로드를 특정하는 표준 레이블 조합. io.kubernetes.pod.namespace 등 메타
# 레이블은 워크로드 식별에 안 쓰이므로 제외.
_ISOLATION_LABEL_KEYS = {"app.kubernetes.io/name", "app.kubernetes.io/instance"}
# temporal처럼 frontend/history/matching/worker가 전부 같은 name+instance를 공유하고
# component만 다른 멀티 컴포넌트 차트(_helpers.tpl: selector.matchLabels에 component
# 포함, 2026-07-16 실측)를 구분하는 데 필요 — 없으면 name+instance만으론 이 넷이
# 전부 "temporal" 하나로 뭉개진다.
_COMPONENT_LABEL_KEY = "app.kubernetes.io/component"
# app.kubernetes.io/* 컨벤션 자체가 없는 손수 작성 매니페스트 폴백 — slack-hitl/
# dummy-monitoring-agent(둘 다 라벨이 app: 하나뿐, 실측 확인)는 이게 없으면 워크로드를
# 영원히 특정 못 해 destination_workload_name이 항상 공백, 격리도 불가했다(2026-07-16).
_FALLBACK_LABEL_KEY = "app"
_PARSEABLE_LABEL_KEYS = _ISOLATION_LABEL_KEYS | {_COMPONENT_LABEL_KEY, _FALLBACK_LABEL_KEY}


def parse_isolation_labels(labels: list[str]) -> dict[str, str]:
    """Hubble flow의 labels(["k8s:키=값", ...])에서 격리 셀렉터로 쓸 표준 레이블을
    추출한다. k8s: 접두어를 뗀 뒤:
      1) app.kubernetes.io/name + instance(+있으면 component) — Helm 차트 컨벤션.
      2) 1)이 안 되면 app 하나만 — app.kubernetes.io/*가 없는 손수 작성 매니페스트 폴백.
    activities.py의 lookback_network_flows가 Loki에서 받은 source/destination.labels를
    여기로 넘긴다. 이 함수 자체는 파싱만 하는 순수 함수라 단위테스트하기 쉽다.
    둘 다 없으면 워크로드를 특정할 수 없어 빈 dict 반환(호출부가 격리 불가로 처리)."""
    parsed: dict[str, str] = {}
    for raw in labels:
        key_value = raw.removeprefix("k8s:")
        key, sep, value = key_value.partition("=")
        if sep and key in _PARSEABLE_LABEL_KEYS:
            parsed[key] = value
    if _ISOLATION_LABEL_KEYS <= parsed.keys():
        keep = _ISOLATION_LABEL_KEYS | {_COMPONENT_LABEL_KEY}
        return {k: v for k, v in parsed.items() if k in keep}
    if _FALLBACK_LABEL_KEY in parsed:
        return {_FALLBACK_LABEL_KEY: parsed[_FALLBACK_LABEL_KEY]}
    return {}


def resolve_workload_name(isolation_labels: dict[str, str]) -> str:
    """parse_isolation_labels 결과 → 사슬 매칭/카드 표시용 단일 문자열 식별자로 합성.

    2026-07-16 실측으로 확정: Hubble이 source 쪽에서 native로 주는 workloads[].name
    (owner-reference 기반, 예: "temporal-frontend")과 destination 쪽 레이블 재구성값이
    같은 물리 파드인데도 서로 달랐다(destination은 기존에 instance만 써서 "temporal"로
    뭉개짐). 이 레포 Helm 차트 다수가 "{release 이름}-{component}"를 실제 리소스 이름으로
    쓰는 컨벤션이라(temporal.componentname 등 _helpers.tpl 패턴, temporal-frontend로
    실측 확인) instance+component를 그 형태로 합성하면 두 경로가 같은 값을 낸다.
    app.kubernetes.io/*가 없으면(app 폴백) app 값을 그대로 canonical 이름으로 쓴다."""
    if "app.kubernetes.io/instance" in isolation_labels:
        instance = isolation_labels["app.kubernetes.io/instance"]
        component = isolation_labels.get(_COMPONENT_LABEL_KEY, "")
        return f"{instance}-{component}" if component else instance
    return isolation_labels.get(_FALLBACK_LABEL_KEY, "")


def parse_hubble_flow(raw: dict) -> dict | None:
    """Loki에서 받은 Hubble flow(JSON) 한 줄 → 판정 재료 dict. DROPPED verdict가 아니면
    None(hubble.export의 allowList가 DROPPED만 내보내지만, 방어적으로 다시 확인).

    표준 Hubble export 포맷(GetFlowsResponse, "flow" 키로 감싸짐) — source/destination
    실측 확인됨(destination도 namespace/pod_name/labels를 source와 동일하게 가짐).
    단, destination엔 source와 달리 workloads 필드가 없음(실측 확인) — 그래서 destination
    워크로드 식별자는 라벨 조합에서 직접 뽑는다(parse_isolation_labels + resolve_workload_name
    재사용). instance만 쓰면 안 되고 component까지 합성해야 source의 workloads[0].name
    (owner-reference 기반 실제 리소스 이름)과 값이 일치한다 — 2026-07-16 실측: temporal
    frontend/history/matching/worker가 전부 같은 name+instance="temporal"을 공유해서
    component 없이는 destination_workload_name이 넷 다 "temporal"로 뭉개지고, source
    쪽 workload_name("temporal-frontend")과 값이 갈려 union-find가 같은 파드를 다른
    워크로드로 취급했다.

    threat_type은 여기서 안 정한다 — 단일 레코드로는 포트스캔(다중 레코드 상관 필요)을 못
    가리므로, lookback_network_flows가 여러 레코드를 워크로드+목적지 카테고리(classify_destination_category)
    로 묶은 뒤 분류한다."""
    flow = raw.get("flow", raw)
    if flow.get("verdict") != "DROPPED":
        return None

    source = flow.get("source") or {}
    destination = flow.get("destination") or {}
    l4 = flow.get("l4") or {}
    tcp_or_udp = l4.get("TCP") or l4.get("UDP") or {}
    ip = flow.get("IP") or {}
    workloads = source.get("workloads") or [{}]
    destination_labels = destination.get("labels") or []
    destination_isolation_labels = parse_isolation_labels(destination_labels)

    return {
        "time": flow.get("time", ""),
        "drop_reason_desc": flow.get("drop_reason_desc", ""),
        "namespace": source.get("namespace", "unknown"),
        "source_pod": source.get("pod_name", "unknown"),
        "source_labels": source.get("labels") or [],
        "workload_name": workloads[0].get("name", ""),
        "workload_kind": workloads[0].get("kind", ""),
        "destination_namespace": destination.get("namespace", "unknown"),
        "destination_pod": destination.get("pod_name", "unknown"),
        # 워크로드 건너가는 사슬(A→B) 연결용 — 비어 있으면(라벨로 특정 불가) 목적지
        # 워크로드를 특정 못 하는 것(예: 클러스터 밖, 또는 app.kubernetes.io/*도 app도
        # 없는 워크로드) — 호출부가 이 경우 edge를 안 긋는다.
        "destination_workload_name": resolve_workload_name(destination_isolation_labels),
        "destination_labels": destination_labels,
        "source_ip": ip.get("source", "0.0.0.0"),
        "destination_ip": ip.get("destination", "0.0.0.0"),
        "destination_port": int(tcp_or_udp.get("destination_port", 0) or 0),
        "protocol": "udp" if "UDP" in l4 else "tcp",
    }


def parse_reserved_identity(labels: list[str]) -> str:
    """Hubble 라벨에서 reserved:* 식별자(kube-apiserver/world/unmanaged 등)를 뽑는다.
    파드가 아닌 소스(EKS 컨트롤플레인 ENI, 클러스터 밖, Cilium 미관리 파드)는 pod_name/
    workload가 비어("unknown"/"") 이 식별자가 유일한 단서다 — 카드 렌더링(workflow.py)이
    "알 수 없음" 대신 이 값을 보여줘야 운영자가 판단할 수 있다(2026-07-16 확정).
    여러 reserved: 라벨이 동시에 있으면(예: kube-apiserver+world) 첫 번째만 쓴다."""
    for label in labels:
        if label.startswith("reserved:"):
            return label.removeprefix("reserved:")
    return ""


def classify_destination_category(destination_labels: list[str]) -> str | None:
    """레코드 하나의 목적지가 클러스터 밖/안 중 어느 쪽인지 destination.labels로 판별한다
    (IP 대역 체크 안 함, 설계 결정). "reserved:world"가 있으면 "external"(클러스터 밖).
    "k8s:" 레이블(클러스터 내부 pod/서비스)이 있으면 "internal". 어느 쪽도 아니면(다른
    reserved 식별자 등) None — 판정 제외(추측으로 잘못 분류 안 함).

    같은 워크로드라도 목적지가 external인 레코드와 internal인 레코드는 서로 다른 threat_type
    후보(abnormal_outbound vs port_scan/lateral_movement)라 반드시 레코드 단위로 갈라야 한다 —
    워크로드 전체를 대표 레코드 하나로만 보면 같은 창에서 스캔+외부유출이 같이 일어나도
    한쪽이 다른 쪽에 묻힌다. lookback_network_flows가 이 카테고리로 먼저 그룹을 나눈 뒤,
    "internal" 그룹 안에서만 distinct destination_port 수로 port_scan/lateral_movement를 가른다."""
    if any("reserved:world" in label for label in destination_labels):
        return "external"
    if any(label.startswith("k8s:") for label in destination_labels):
        return "internal"
    return None


def dedup_events(events: list[SecurityEvent]) -> list[SecurityEvent]:
    """CloudTrail eventid 기준 dedup(첫 등장분 유지). 순수 함수(I/O 없음) —
    workflow.py가 개별 판정(map_regulation) 호출 전에 직접 불러 중복 호출을 막는다."""
    seen: set[str] = set()
    deduped: list[SecurityEvent] = []
    for event in events:
        event_id = extract_evidence(event).get("cloudtrail_event_id", "")
        key = event_id or event.raw_log  # eventid 없으면(비정상 파싱) raw_log로 폴백 dedup
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def build_incident_group(
    workflow_id: str,
    scenario: str,
    correlation_key: str,
    events: list[SecurityEvent],
    window_start,
    window_end,
) -> "IncidentGroup":
    """lookback 상관분석 — dedup_events 재적용(멱등) 후 IncidentGroup 구성. 시나리오 공용
    (scenario="account_takeover"|"intrusion") — correlation_key는 호출부가 시나리오에 맞는
    값(IAM User ARN 또는 워크로드 이름)을 채운다. 순수 함수(I/O 없음) — Rule Filter와
    동일하게 workflow.py에서 직접 호출 가능."""
    from contracts.models import IncidentGroup

    return IncidentGroup(
        workflow_id=workflow_id,
        scenario=scenario,
        correlation_key=correlation_key,
        events=dedup_events(events),
        window_start=window_start,
        window_end=window_end,
    )
