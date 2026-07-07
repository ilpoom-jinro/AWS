from __future__ import annotations

import json
import os
import subprocess
from typing import Any


AGENT_KEY = "cluster_state"
AGENT_NAME = "Cluster State Agent"
LLM_PROMPT = None

EVENT_NAMESPACES = {"finops-mas", "app", "payment", "kube-system"}


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    deployments = collect_all_deployments()
    hpa_map = collect_hpa_info()
    spot_prices = collect_spot_prices()
    rds_metrics = collect_rds_metrics()
    scale_target = collect_scale_target_pods()

    idle_candidates: list[dict[str, Any]] = []
    total_saving = 0.0

    for deployment in deployments:
        namespace = deployment["namespace"]
        name = deployment["name"]
        current = int(deployment.get("current_replicas") or 0)

        if namespace in EVENT_NAMESPACES:
            continue

        hpa = hpa_map.get(f"{namespace}/{name}")
        hpa_min = int(hpa["min"]) if hpa else 1
        reducible = max(0, current - hpa_min)
        if reducible <= 0:
            continue

        spot_price = float(spot_prices.get("m5.xlarge", 0.15))
        event_hours = 2.0
        saving = round(reducible * spot_price * event_hours, 2)
        total_saving += saving
        idle_candidates.append(
            {
                "namespace": namespace,
                "deployment": name,
                "current_replicas": current,
                "hpa_min": hpa_min,
                "reducible_replicas": reducible,
                "estimated_saving_usd": saving,
                "risk": "low" if reducible <= 2 else "medium",
            }
        )

    total_cluster_pods = sum(int(item.get("current_replicas") or 0) for item in deployments)
    event_pods = sum(
        int(item.get("current_replicas") or 0)
        for item in deployments
        if item.get("namespace") in EVENT_NAMESPACES
    )
    result = {
        "total_cluster_pods": total_cluster_pods,
        "total_event_related_pods": event_pods,
        "idle_candidates": idle_candidates,
        "idle_candidate_count": len(idle_candidates),
        "total_reducible_pods": sum(item["reducible_replicas"] for item in idle_candidates),
        "total_estimated_saving_usd": round(total_saving, 2),
        "spot_price_m5xlarge": float(spot_prices.get("m5.xlarge", 0.15)),
        "source": "kubectl+aws_api",
        "scale_target": scale_target,
        "scale_target_current_pods": (
            scale_target.get("current_replicas")
            or event_pods
            or 27
        ),
    }
    primary_db = rds_metrics.get("financial-service-db", {})
    result["rds_metrics"] = rds_metrics
    result["rds_cpu_percent"] = primary_db.get("cpu_percent")
    result["rds_connections"] = primary_db.get("connections")
    result["rds_source"] = primary_db.get("source", "unknown")
    message = (
        f"Cluster has {total_cluster_pods} deployment replicas; "
        f"found {len(idle_candidates)} idle resource candidates with "
        f"estimated saving ${total_saving:.2f}."
    )
    return result, message


def collect_scale_target_pods() -> dict[str, Any]:
    namespace = os.getenv("SCALE_TARGET_NAMESPACE", "finops-mas")
    deployment = os.getenv("SCALE_TARGET_DEPLOYMENT", "finops-orchestrator")

    try:
        completed = subprocess.run(
            ["kubectl", "get", "deployment", deployment, "-n", namespace, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0:
            return {
                "namespace": namespace,
                "deployment": deployment,
                "current_replicas": None,
                "ready_replicas": None,
                "source": "kubectl_failed",
            }

        data = json.loads(completed.stdout or "{}")
        spec = data.get("spec", {})
        status = data.get("status", {})
        return {
            "namespace": namespace,
            "deployment": deployment,
            "current_replicas": spec.get("replicas", 0),
            "ready_replicas": status.get("readyReplicas", 0),
            "source": "kubectl",
        }
    except Exception as exc:
        return {
            "namespace": namespace,
            "deployment": deployment,
            "current_replicas": None,
            "ready_replicas": None,
            "source": "kubectl_failed",
            "error": str(exc),
        }


def collect_all_deployments() -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["kubectl", "get", "deployment", "--all-namespaces", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        data = json.loads(completed.stdout or "{}")
        result = []
        for item in data.get("items", []):
            metadata = item.get("metadata", {})
            spec = item.get("spec", {})
            status = item.get("status", {})
            result.append(
                {
                    "namespace": metadata.get("namespace", ""),
                    "name": metadata.get("name", ""),
                    "current_replicas": spec.get("replicas", 0),
                    "ready_replicas": status.get("readyReplicas", 0),
                    "available_replicas": status.get("availableReplicas", 0),
                }
            )
        return result
    except Exception:
        return []


def collect_hpa_info() -> dict[str, dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["kubectl", "get", "hpa", "--all-namespaces", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        data = json.loads(completed.stdout or "{}")
        result: dict[str, dict[str, Any]] = {}
        for item in data.get("items", []):
            metadata = item.get("metadata", {})
            spec = item.get("spec", {})
            status = item.get("status", {})
            namespace = metadata.get("namespace", "")
            name = metadata.get("name", "")
            if not namespace or not name:
                continue
            result[f"{namespace}/{name}"] = {
                "min": spec.get("minReplicas", 1),
                "max": spec.get("maxReplicas", 10),
                "current": status.get("currentReplicas", 0),
            }
        return result
    except Exception:
        return {}


def collect_spot_prices() -> dict[str, float]:
    try:
        import boto3

        region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2"))
        ec2 = boto3.client("ec2", region_name=region)
        response = ec2.describe_spot_price_history(
            InstanceTypes=["m5.xlarge", "m5.2xlarge"],
            ProductDescriptions=["Linux/UNIX"],
            MaxResults=10,
        )
        prices: dict[str, float] = {}
        for item in response.get("SpotPriceHistory", []):
            instance_type = item.get("InstanceType")
            if instance_type and instance_type not in prices:
                prices[instance_type] = float(item["SpotPrice"])
        return prices
    except Exception:
        return {"m5.xlarge": 0.15, "m5.2xlarge": 0.28}


def collect_rds_metrics() -> dict[str, dict[str, Any]]:
    try:
        import boto3
        from datetime import datetime, timedelta, timezone
    except Exception as exc:
        return {
            db_id: {
                "cpu_percent": None,
                "connections": None,
                "source": "cloudwatch_failed",
                "error": str(exc),
            }
            for db_id in ["financial-service-db", "financial-ops-db"]
        }

    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2"))
    rds_instances = ["financial-service-db", "financial-ops-db"]
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=10)
    result: dict[str, dict[str, Any]] = {}

    try:
        cloudwatch = boto3.client("cloudwatch", region_name=region)
    except Exception as exc:
        return {
            db_id: {
                "cpu_percent": None,
                "connections": None,
                "source": "cloudwatch_failed",
                "error": str(exc),
            }
            for db_id in rds_instances
        }

    for db_id in rds_instances:
        try:
            cpu_percent = _latest_cloudwatch_average(
                cloudwatch,
                namespace="AWS/RDS",
                metric_name="CPUUtilization",
                dimension_name="DBInstanceIdentifier",
                dimension_value=db_id,
                start_time=start_time,
                end_time=end_time,
            )
            connections = _latest_cloudwatch_average(
                cloudwatch,
                namespace="AWS/RDS",
                metric_name="DatabaseConnections",
                dimension_name="DBInstanceIdentifier",
                dimension_value=db_id,
                start_time=start_time,
                end_time=end_time,
            )
            result[db_id] = {
                "cpu_percent": round(cpu_percent, 1) if cpu_percent is not None else None,
                "connections": round(connections) if connections is not None else None,
                "source": "cloudwatch",
            }
        except Exception as exc:
            result[db_id] = {
                "cpu_percent": None,
                "connections": None,
                "source": "cloudwatch_failed",
                "error": str(exc),
            }
    return result


def _latest_cloudwatch_average(
    cloudwatch: Any,
    *,
    namespace: str,
    metric_name: str,
    dimension_name: str,
    dimension_value: str,
    start_time: Any,
    end_time: Any,
) -> float | None:
    response = cloudwatch.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=[{"Name": dimension_name, "Value": dimension_value}],
        StartTime=start_time,
        EndTime=end_time,
        Period=300,
        Statistics=["Average"],
    )
    datapoints = response.get("Datapoints", [])
    if not datapoints:
        return None
    latest = sorted(datapoints, key=lambda item: item["Timestamp"])[-1]
    return float(latest["Average"])


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
