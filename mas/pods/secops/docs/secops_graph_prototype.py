"""
SecOps Agent - LangGraph 뼈대 v2 (시나리오 C) — 조건 분기 추가
==============================================================

v1 대비 바뀐 점:
    - 일직선 그래프 → "조건 분기(conditional edges)" 추가.
      LangGraph의 진짜 가치(분기/루프)를 쓰는 첫 버전.
    - map_regulation 분석 결과에 따라 경로가 갈림:
        위반 아님            → 종료 (no_action)
        위반 + 격리 위험      → 사람 검토 에스컬레이션 (escalate)
        위반 + 격리 안전      → 격리/보고 진행 (isolate)
    - 격리 정책: Istio AuthorizationPolicy (민수님 확인)

여전히 RAG·Claude·격리는 stub. AWS/클러스터 없이 로컬에서 그냥 돌아감.
실제 Bedrock:  USE_REAL_BEDROCK=true python secops_graph_prototype.py

실행:
    1) 이 파일을 레포의 mas/ 안에 둔다 (contracts/ 와 같은 레벨)
    2) pip install langgraph
    3) python secops_graph_prototype.py
"""

from __future__ import annotations

import os
import sys
from typing import TypedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.graph import StateGraph, START, END

from contracts.models import (
    AnomalyReport,
    ApprovalRequest,
    ComplianceReport,
    DetectThreatInput,
    ExecutionResult,
    RegulationMapping,
    SecurityEvent,
)

USE_REAL_BEDROCK = os.getenv("USE_REAL_BEDROCK", "false").lower() == "true"


# =====================================================================
# LangGraph State
#   노드 사이를 흐르는 작업 메모리. 각 노드는 바꾼 키만 dict로 return.
#   _demo_case 는 데모 전용(실제 구현엔 없음) — 입력에 따라 분기를 보여주려는 용도.
# =====================================================================
class SecOpsState(TypedDict, total=False):
    detect_input: DetectThreatInput
    event: SecurityEvent
    retrieved_regulations: list[str]
    mapping: RegulationMapping
    decision: str                 # "no_action" | "escalate" | "isolate"
    execution_result: ExecutionResult
    report: ComplianceReport
    _demo_case: str               # 데모 전용


# =====================================================================
# 노드 1) detect_threat  (대응: SecOpsActivities.detect_threat)
# =====================================================================
def detect_threat_node(state: SecOpsState) -> dict:
    inp = state["detect_input"]

    # --- 데모 전용: 케이스별로 다른 이벤트를 만들어 분기를 보여줌 ---
    # 주의: stub이 destination_ip.is_private로 외부/내부를 가르므로
    #       "외부" 예시는 진짜 공인 IP를 써야 함 (203.0.113.x 등 문서용 대역은
    #       Python 3.12+에서 is_private=True로 잡혀 내부로 오인됨)
    case = state.get("_demo_case", "exfil_external")
    if case == "exfil_kube_system":          # 외부 유출 + 시스템 영향 → 위험
        namespace, destination = "kube-system", "104.18.0.2"
    elif case == "internal_falsepos":         # 내부 트래픽 → 위반 아님(오탐)
        namespace, destination = "financial-api", "10.4.5.6"
    else:                                     # exfil_external: 외부 유출 + 안전
        namespace, destination = "financial-api", "104.18.0.1"
    # --- 실제 구현에선 위 분기 대신 VPC Flow Logs/CloudTrail 조회 결과로 채움 ---

    event = SecurityEvent(
        cluster_name=inp.cluster_name,        # workflow_id 자동 생성
        namespace=namespace,
        source_pod="payment-worker-7d9f",
        source_ip="10.0.12.34",
        destination_ip=destination,
        destination_port=8443,
        protocol="tcp",
        direction="outbound",
        threat_type="abnormal_outbound",
        raw_log=f"[flowlog] 10.0.12.34 -> {destination}:8443 ACCEPT 1.2MB/5s",
    )
    print(f"[detect_threat] event 생성 (ns={namespace}, dst={destination}) "
          f"workflow_id={event.workflow_id}")
    return {"event": event}


# =====================================================================
# 노드 2) map_regulation  ← SecOps 핵심 (대응: SecOpsActivities.map_regulation)
# =====================================================================
def retrieve_regulations(event: SecurityEvent) -> list[str]:
    """RAG stub. 실제로는 Bedrock Knowledge Base retrieve (S3 규정 문서)."""
    return [
        "전자금융감독규정 제13조 (해킹 등 방지대책)",
        "신용정보법 제19조 (신용정보전산시스템의 안전보호)",
    ]


def analyze_violation(event: SecurityEvent, regulations: list[str]) -> dict:
    """위반 여부 분석. 기본 stub, USE_REAL_BEDROCK=true면 실제 Claude 호출."""
    if not USE_REAL_BEDROCK:
        # stub 규칙: 내부(private) IP로의 트래픽은 오탐으로 간주
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
    """실제 Bedrock 호출 (팀 공통 SDK, FinOps와 동일 경로). JSON만 받아 파싱."""
    import json
    from shared.bedrock import ClaudeModel, get_bedrock_client

    model_id = os.getenv("BEDROCK_MODEL", ClaudeModel.HAIKU.value)  # 개발 기본 Haiku
    client = get_bedrock_client()

    system_prompt = (
        "너는 금융 보안 규제 분석기다. 주어진 보안 이벤트가 제시된 규정을 위반하는지 판단해라. "
        "반드시 아래 JSON 스키마만 출력하고 다른 텍스트는 절대 출력하지 마라.\n"
        '{"violated_regulations": [string], "violation_description": string}\n'
        "위반이 아니면 violated_regulations는 빈 배열로."
    )
    user_text = (
        f"[보안 이벤트]\n{event.model_dump_json(indent=2)}\n\n"
        "[검토 대상 규정]\n" + "\n".join(f"- {r}" for r in regulations)
    )

    resp = client.converse(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        inferenceConfig={"maxTokens": 1024, "temperature": 0},  # 결정적 JSON
    )

    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"]).strip()
    if text.startswith("```"):                      # ```json 펜스 제거
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    data = json.loads(text[text.find("{"): text.rfind("}") + 1])

    return {  # map_regulation이 기대하는 dict 형태 그대로 (흐름 불변)
        "violated_regulations": list(data.get("violated_regulations", [])),
        "violation_description": str(data.get("violation_description", "")),
    }

def check_blast_radius(event: SecurityEvent) -> tuple[bool, str]:
    """오탐/2차피해 방지 시뮬레이션 stub. 격리해도 안전한지 판단."""
    safe = event.namespace != "kube-system"
    detail = ("단일 worker pod 격리, 동일 서비스 다른 replica가 처리 가능 → 안전"
              if safe else "시스템 네임스페이스(kube-system) 영향 → 위험")
    return safe, detail


def build_isolation_policy(event: SecurityEvent) -> str:
    """
    격리 정책 YAML (Istio). 민수님 확인: 이 프로젝트는 Istio 사용.
    참고: 이번처럼 outbound 유출이 핵심이면 엄격한 egress 차단을 위해
          Sidecar egress 제한을 함께 거는 것도 검토 (PR에서 확정).
    """
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
    - {{}}   # 빈 규칙 = 매칭된 워크로드의 모든 요청 차단(격리)
"""


def map_regulation_node(state: SecOpsState) -> dict:
    event = state["event"]

    regulations = retrieve_regulations(event)
    analysis = analyze_violation(event, regulations)
    safe, detail = check_blast_radius(event)

    mapping = RegulationMapping(
        workflow_id=event.workflow_id,          # ★ 같은 workflow_id 전파
        violated_regulations=analysis["violated_regulations"],
        violation_description=analysis["violation_description"],
        blast_radius_safe=safe,
        blast_radius_detail=detail,
        isolation_policy_yaml=build_isolation_policy(event),
    )

    # 분석 결과로 다음 경로 결정 (이 값을 분기 함수가 읽음)
    if not mapping.violated_regulations:
        decision = "no_action"
    elif not mapping.blast_radius_safe:
        decision = "escalate"
    else:
        decision = "isolate"

    print(f"[map_regulation] 위반 {len(mapping.violated_regulations)}건, "
          f"safe={mapping.blast_radius_safe} → decision={decision}")
    return {"retrieved_regulations": regulations, "mapping": mapping, "decision": decision}


# =====================================================================
# 분기 함수: map_regulation 다음에 어디로 갈지 결정
#   (LangGraph add_conditional_edges 에 넘길 라우터. 부수효과 없이 키만 반환)
# =====================================================================
def route_after_mapping(state: SecOpsState) -> str:
    return state["decision"]


# =====================================================================
# 노드) human_escalation  (escalate 경로 전용 stub)
#   실제: blast radius 위험 → 자동격리 보류하고 Slack로 사람 검토 요청
# =====================================================================
def human_escalation_node(state: SecOpsState) -> dict:
    event = state["event"]
    print(f"[human_escalation] 격리 위험 → Slack으로 사람 검토 요청, 자동격리 보류 "
          f"(pod={event.source_pod}, stub)")
    return {}


# =====================================================================
# 노드 3) generate_report  (대응: SecOpsActivities.generate_compliance_report)
#   decision에 따라 다른 보고서 생성. (no_action 경로는 여기 안 옴)
# =====================================================================
def generate_report_node(state: SecOpsState) -> dict:
    event = state["event"]
    mapping = state["mapping"]
    decision = state["decision"]

    if decision == "isolate":
        # 실제로는 [승인 → apply_isolation Activity]가 워크플로우에서 돌고 결과가 여기로.
        # 프로토타입에선 적용됐다고 가정.
        isolation_applied = True
        action = "승인 후 Istio AuthorizationPolicy 적용으로 pod 격리 (apply_isolation, 적용 가정)"
    else:  # escalate
        isolation_applied = False
        action = "blast radius 위험으로 사람 검토 에스컬레이션, 자동격리 보류"

    execution_result = ExecutionResult(
        workflow_id=event.workflow_id,
        success=isolation_applied,
        action_taken=action,
        output="isolated" if isolation_applied else "held_for_human",
    )
    report = ComplianceReport(
        workflow_id=event.workflow_id,          # ★ 동일 workflow_id 유지
        severity="high",
        violated_regulations=mapping.violated_regulations,
        threat_summary=f"{event.threat_type} from {event.source_pod}",
        action_taken=action,
        isolation_applied=isolation_applied,
    )
    print(f"[generate_report] decision={decision}, isolation_applied={isolation_applied}")
    return {"execution_result": execution_result, "report": report}


# =====================================================================
# 그래프 조립
#   START → detect → map → (분기) → ...
#     no_action → END
#     escalate  → human_escalation → generate_report → END
#     isolate   → generate_report → END
# =====================================================================
def build_secops_graph():
    g = StateGraph(SecOpsState)
    g.add_node("detect_threat", detect_threat_node)
    g.add_node("map_regulation", map_regulation_node)
    g.add_node("human_escalation", human_escalation_node)
    g.add_node("generate_report", generate_report_node)

    g.add_edge(START, "detect_threat")
    g.add_edge("detect_threat", "map_regulation")
    g.add_conditional_edges(
        "map_regulation",
        route_after_mapping,
        {
            "no_action": END,               # 위반 아님 → 종료
            "escalate": "human_escalation", # 위험 → 사람에게
            "isolate": "generate_report",   # 안전 → 격리/보고
        },
    )
    g.add_edge("human_escalation", "generate_report")
    g.add_edge("generate_report", END)
    return g.compile()


def demo_workflow_layer(event: SecurityEvent, mapping: RegulationMapping) -> None:
    """참고: 워크플로우 레이어가 만드는 계약 모델(AnomalyReport/ApprovalRequest) 사용법."""
    AnomalyReport(
        workflow_id=event.workflow_id, scenario="secops",
        anomaly_type="regulation_breach", severity="high",
        affected_resource=event.source_pod,
        summary="비정상 outbound로 인한 규제 위반 의심",
        detail=mapping.violation_description, confidence=0.82,
        regulation_mapping=mapping,        # finops/aiops 플랜 넣으면 ValidationError
    )
    ApprovalRequest(
        workflow_id=event.workflow_id, scenario="secops", severity="high",
        summary="보안 격리 승인 요청", detail="해당 pod outbound 차단을 적용해도 될까요?",
        regulation_mapping=mapping,        # secops는 regulation_mapping 필수
    )
    print("[workflow] AnomalyReport+ApprovalRequest 생성 OK (validator 통과)")


if __name__ == "__main__":
    print(f"USE_REAL_BEDROCK = {USE_REAL_BEDROCK}\n" + "=" * 64)
    app = build_secops_graph()

    print("── 분기 데모: 같은 그래프, 다른 입력 → 다른 경로 ──")
    for case, desc in [
        ("exfil_external",    "외부 유출 / 격리 안전"),
        ("exfil_kube_system", "외부 유출 / 격리 위험"),
        ("internal_falsepos", "내부 트래픽 / 위반 아님"),
    ]:
        r = app.invoke({
            "detect_input": DetectThreatInput(cluster_name="financial-ops-eks", vpc_id="vpc-0a1b2c3d"),
            "_demo_case": case,
        })
        print(f"  → [{case:17}] {desc:18} decision={r.get('decision'):10} "
              f"report={'O' if 'report' in r else 'X'}\n")

    print("=" * 64)
    print("상세 출력 (isolate 케이스):")
    final = app.invoke({
        "detect_input": DetectThreatInput(cluster_name="financial-ops-eks", vpc_id="vpc-0a1b2c3d"),
        "_demo_case": "exfil_external",
    })
    event, mapping, report = final["event"], final["mapping"], final["report"]
    demo_workflow_layer(event, mapping)

    print("-" * 64)
    print("E2E 추적 — 세 모델 workflow_id 일치 여부:")
    print(f"  SecurityEvent     : {event.workflow_id}")
    print(f"  RegulationMapping : {mapping.workflow_id}")
    print(f"  ComplianceReport  : {report.workflow_id}")
    assert event.workflow_id == mapping.workflow_id == report.workflow_id
    print("  ✓ 일치\n")

    print("최종 ComplianceReport:")
    print(report.model_dump_json(indent=2))