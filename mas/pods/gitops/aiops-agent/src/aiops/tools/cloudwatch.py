"""
tools/cloudwatch.py — CloudWatch Logs/Metrics 래퍼
VPC Endpoint 경유로 CloudWatch에서 EKS 컨트롤 플레인 로그와
커스텀 메트릭을 조회한다.
"""
from __future__ import annotations

import time
from typing import Any

import boto3


class CloudWatchClient:
    def __init__(self, region: str = "ap-northeast-2") -> None:
        self._logs = boto3.client("logs", region_name=region)
        self._metrics = boto3.client("cloudwatch", region_name=region)

    # ── Logs ─────────────────────────────────────────────────────

    def get_eks_control_plane_logs(
        self,
        cluster_name: str,
        log_stream_prefix: str = "kube-controller-manager",
        minutes: int = 10,
        limit: int = 100,
    ) -> list[str]:
        """
        EKS 컨트롤 플레인 로그 조회.
        /aws/eks/<cluster>/cluster 로그 그룹에서 최근 N분 이벤트 반환.
        """
        log_group = f"/aws/eks/{cluster_name}/cluster"
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - minutes * 60 * 1000

        try:
            resp = self._logs.filter_log_events(
                logGroupName=log_group,
                logStreamNamePrefix=log_stream_prefix,
                startTime=start_ms,
                endTime=end_ms,
                limit=limit,
            )
            return [e["message"] for e in resp.get("events", [])]
        except Exception as exc:
            return [f"[CW Logs 조회 실패: {exc}]"]

    def get_pod_logs_from_cw(
        self,
        cluster_name: str,
        namespace: str,
        pod_name: str,
        minutes: int = 5,
    ) -> list[str]:
        """
        Fluent Bit가 CW로 전송한 파드 로그 조회.
        로그 그룹: /aws/containerinsights/<cluster>/application
        """
        log_group = f"/aws/containerinsights/{cluster_name}/application"
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - minutes * 60 * 1000

        try:
            resp = self._logs.filter_log_events(
                logGroupName=log_group,
                logStreamNamePrefix=f"{namespace}.{pod_name}",
                startTime=start_ms,
                endTime=end_ms,
                limit=200,
            )
            return [e["message"] for e in resp.get("events", [])]
        except Exception as exc:
            return [f"[CW Logs(앱) 조회 실패: {exc}]"]

    # ── Metrics ──────────────────────────────────────────────────

    def get_node_cpu_utilization(
        self, cluster_name: str, node_name: str, minutes: int = 10
    ) -> list[dict[str, Any]]:
        """
        Container Insights의 node_cpu_utilization 메트릭 조회.
        """
        end = time.time()
        start = end - minutes * 60

        try:
            resp = self._metrics.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "cpu",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "ContainerInsights",
                                "MetricName": "node_cpu_utilization",
                                "Dimensions": [
                                    {"Name": "ClusterName", "Value": cluster_name},
                                    {"Name": "NodeName", "Value": node_name},
                                ],
                            },
                            "Period": 60,
                            "Stat": "Average",
                        },
                    }
                ],
                StartTime=start,
                EndTime=end,
            )
            results = resp.get("MetricDataResults", [])
            if results:
                return [
                    {"timestamp": str(t), "value": v}
                    for t, v in zip(
                        results[0].get("Timestamps", []),
                        results[0].get("Values", []),
                    )
                ]
        except Exception as exc:
            return [{"error": str(exc)}]
        return []
