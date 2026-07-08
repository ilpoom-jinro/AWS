"""
텔레메트리 재조회 (VPC Flow Logs / CloudTrail)
==============================================
CloudWatch Alarm은 신호만 주므로, Flow Logs를 재조회해 실제 REJECT 레코드
(출발지/목적지/포트)로 SecurityEvent를 보강한다. SecOps 전용 IAM role의
logs:StartQuery / GetQueryResults / ec2:DescribeFlowLogs 권한을 사용.

전부 best-effort: 조회 실패 시 {} 반환 → 호출자는 신호 기반으로 진행.
boto3 실호출은 클러스터 내부(IAM role)에서만 동작.
"""

from __future__ import annotations

import os
import time

REGION = os.getenv("AWS_REGION", "ap-northeast-2")
# Flow Logs가 나가는 CloudWatch Logs 그룹 (configmap SECOPS_FLOWLOG_GROUP로 주입).
FLOW_LOG_GROUP = os.getenv("SECOPS_FLOWLOG_GROUP", "/aws/vpc/flowlogs/vpc1")


def enrich_flow_logs(parsed: dict, lookback_min: int = 10, limit: int = 5) -> dict:
    """
    Flow Logs Insights로 최근 REJECT 레코드 top N을 조회해 상세를 보강.
    반환: SecurityEvent 필드 보강 dict (+ evidence). 실패 시 {}.
    """
    import boto3

    logs = boto3.client("logs", region_name=REGION)
    end = int(time.time())
    start = end - lookback_min * 60

    # 외부 유출/거부 트래픽 상위 조회 (Flow Logs 표준 필드)
    query = (
        "fields srcAddr, dstAddr, dstPort, protocol, action, bytes "
        "| filter action = 'REJECT' "
        "| stats sum(bytes) as total by srcAddr, dstAddr, dstPort "
        "| sort total desc "
        f"| limit {limit}"
    )
    try:
        qid = logs.start_query(
            logGroupName=FLOW_LOG_GROUP,
            startTime=start,
            endTime=end,
            queryString=query,
        )["queryId"]

        # 폴링 (Insights는 비동기)
        for _ in range(20):
            res = logs.get_query_results(queryId=qid)
            if res["status"] in ("Complete", "Failed", "Cancelled"):
                break
            time.sleep(1)

        rows = res.get("results", [])
        if not rows:
            return {}

        top = {c["field"]: c["value"] for c in rows[0]}
        return {
            "source_ip": top.get("srcAddr", "0.0.0.0"),
            "destination_ip": top.get("dstAddr", "0.0.0.0"),
            "destination_port": int(top.get("dstPort", 0) or 0) or 1,
            "direction": "outbound",
            "confidence": 0.7,
            "evidence": {
                "flow_log_group": FLOW_LOG_GROUP,
                "flow_log_query_id": qid,
                "flow_log_top_talker": top,
                "flow_log_matches": len(rows),
            },
        }
    except Exception:  # noqa: BLE001  권한/그룹/네트워크 문제 → 신호 기반 진행
        return {}
