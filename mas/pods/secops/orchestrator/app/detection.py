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
    """SQS body(JSON) → 'alarm' | 'eventbridge' | 'unknown'."""
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
            # Rule Filter(workflow.py)의 권한부여 위험도 판단용 — 계정 탈취 대응
            "policy_arn": request_params.get("policyArn", ""),
            "target_user": request_params.get("userName", ""),
            "target_role": request_params.get("roleName", ""),
            "target_group": request_params.get("groupName", ""),
        },
    }


def parse_message(body: str) -> dict | None:
    """SQS body → 파싱 결과 dict (kind 포함). 파싱 불가 시 None."""
    kind = classify_message(body)
    data = json.loads(body) if kind != "unknown" else None
    if kind == "alarm":
        return {"kind": kind, **parse_alarm(data)}
    if kind == "eventbridge":
        return {"kind": kind, **parse_eventbridge(data)}
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
