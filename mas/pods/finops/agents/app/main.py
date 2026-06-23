import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

import boto3
import psycopg
from botocore.config import Config
from fastapi import FastAPI
from pydantic import BaseModel, Field
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.agent_dispatch import run_agent as run_finops_agent_logic
from app.agent_support import AGENT_TASK_QUEUES


AGENT_KEY = os.getenv("AGENT_KEY", "business_control")
AGENT_NAME = os.getenv("AGENT_NAME", "Business Control Agent")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://finops:finops@finops-db.finops-mas.svc.cluster.local:5432/finops",
)
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "finops-temporal.finops-mas.svc.cluster.local:7233")
AGENT_TASK_QUEUE = os.getenv(
    "AGENT_TASK_QUEUE",
    AGENT_TASK_QUEUES.get(AGENT_KEY, f"finops-{AGENT_KEY.replace('_', '-')}-agent-task-queue"),
)
FINOPS_NAMESPACE = os.getenv("FINOPS_NAMESPACE", "finops-mas")
FINOPS_APP_LABEL = os.getenv("FINOPS_APP_LABEL", "app.kubernetes.io/part-of=finops-mas")
FINOPS_UI_DEPLOYMENT = os.getenv("FINOPS_UI_DEPLOYMENT", "finops-ui")
FINOPS_KUBECTL_BIN = os.getenv("FINOPS_KUBECTL_BIN", "kubectl")
FINOPS_AWS_BIN = os.getenv("FINOPS_AWS_BIN", "aws")
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2"))
FINOPS_EKS_CLUSTER_NAME = os.getenv("FINOPS_EKS_CLUSTER_NAME", "financial-ops-eks")
FINOPS_EKS_NODEGROUP_NAME = os.getenv("FINOPS_EKS_NODEGROUP_NAME", "")
FINOPS_SPOT_INSTANCE_TYPES = [
    item.strip()
    for item in os.getenv("FINOPS_SPOT_INSTANCE_TYPES", "m7i-flex.large,m7i.large,m6i.large").split(",")
    if item.strip()
]
COMMAND_COLLECTORS_ENABLED = os.getenv("FINOPS_COMMAND_COLLECTORS_ENABLED", "true").lower() == "true"
COMMAND_COLLECTOR_TIMEOUT_SECONDS = float(os.getenv("FINOPS_COMMAND_COLLECTOR_TIMEOUT_SECONDS", "5"))
FINOPS_ATHENA_DATABASE = os.getenv("FINOPS_ATHENA_DATABASE", "finops_cur")
FINOPS_ATHENA_TABLE = os.getenv("FINOPS_ATHENA_TABLE", "cur")
FINOPS_ATHENA_WORKGROUP = os.getenv("FINOPS_ATHENA_WORKGROUP", "finops-cur")
FINOPS_ATHENA_TIMEOUT_SECONDS = float(os.getenv("FINOPS_ATHENA_TIMEOUT_SECONDS", "10"))

AGENT_DATA_REQUESTS = {
    "demand_shaping": [
        {
            "source_key": "business_control",
            "source_name": "Business Control Agent",
            "field": "max_delay_minutes",
            "label": "일반 사용자 허용 지연 시간",
            "reason": "푸시 분산 구간을 정하려면 정책상 허용 지연 시간이 필요합니다.",
        },
    ],
    "traffic_forecast": [
        {
            "source_key": "demand_shaping",
            "source_name": "Demand Shaping Agent",
            "field": "peak_reduction_percent",
            "label": "분산 발송 후 예상 peak 감소율",
            "reason": "평탄화 후 RPS를 다시 계산하기 위한 보정값입니다.",
        },
        {
            "source_key": "business_control",
            "source_name": "Business Control Agent",
            "field": "target_users",
            "label": "대상 사용자 수",
            "reason": "푸시 대상 규모를 기준으로 원래 peak를 추정합니다.",
        },
    ],
    "bottleneck_capacity": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "peak_rps_after",
            "label": "병목 검증 기준 RPS",
            "reason": "DB/cache/LB가 감당해야 할 트래픽 기준입니다.",
        },
    ],
    "cost": [
        {
            "source_key": "traffic_forecast",
            "source_name": "Traffic Forecast Agent",
            "field": "required_app_pods",
            "label": "비용 계산 기준 pod 수",
            "reason": "임시 비용 모델에서 app pod 수를 비용 산정 기준으로 사용합니다.",
        },
    ],
    "policy_guardrail": [
        {
            "source_key": "cost",
            "source_name": "Cost Agent",
            "field": "total",
            "label": "예상 총 비용",
            "reason": "정책상 승인 또는 차단 여부를 판단합니다.",
        },
    ],
}

AGENT_CONFIDENCE = {
    "business_control": 0.91,
    "demand_shaping": 0.86,
    "traffic_forecast": 0.82,
    "bottleneck_capacity": 0.78,
    "cost": 0.8,
    "policy_guardrail": 0.9,
}

app = FastAPI(title=AGENT_NAME, version="0.3.0")
temporal_worker_task: asyncio.Task | None = None
temporal_client: Client | None = None


class AgentRequest(BaseModel):
    workflow_id: str
    context: dict[str, Any]
    available_results: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect():
    return psycopg.connect(DATABASE_URL, autocommit=True)


def run_readonly_command(name: str, command: list[str]) -> dict[str, Any]:
    if not COMMAND_COLLECTORS_ENABLED:
        return {"name": name, "status": "disabled", "command": command}
    executable = shutil.which(command[0])
    if executable is None:
        return {"name": name, "status": "unavailable", "command": command, "error": f"{command[0]} not found"}
    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            capture_output=True,
            check=False,
            text=True,
            timeout=COMMAND_COLLECTOR_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return {"name": name, "status": "timeout", "command": command, "error": str(exc)}
    return {
        "name": name,
        "status": "ok" if completed.returncode == 0 else "failed",
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def parse_command_json(result: dict[str, Any]) -> dict[str, Any] | None:
    if result.get("status") != "ok" or not result.get("stdout"):
        return None
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        result["status"] = "parse_failed"
        result["error"] = str(exc)
        return None


def first_kubernetes_item(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    items = payload.get("items")
    if isinstance(items, list) and items:
        return items[0]
    return payload if payload.get("kind") else {}


def parse_kubectl_top_pods(stdout: str) -> dict[str, Any]:
    pods = []
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] != "NAME":
            pods.append({"name": parts[0], "cpu": parts[1], "memory": parts[2]})
    return {"pods": pods, "sample_count": len(pods)}


def collect_athena_cost() -> dict[str, Any]:
    command: dict[str, Any] = {
        "name": "athena_cur_mtd",
        "status": "failed",
        "database": FINOPS_ATHENA_DATABASE,
        "table": FINOPS_ATHENA_TABLE,
        "workgroup": FINOPS_ATHENA_WORKGROUP,
    }
    if not COMMAND_COLLECTORS_ENABLED:
        command["status"] = "disabled"
        return _athena_result(command)
    identifier = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    if not identifier.fullmatch(FINOPS_ATHENA_DATABASE) or not identifier.fullmatch(FINOPS_ATHENA_TABLE):
        command["error"] = "Athena database and table names must be SQL identifiers"
        return _athena_result(command)

    query = (
        'SELECT COALESCE(SUM(CAST("line_item_unblended_cost" AS DOUBLE)), 0) '
        f'AS month_to_date_usd FROM "{FINOPS_ATHENA_DATABASE}"."{FINOPS_ATHENA_TABLE}" '
        'WHERE CAST("line_item_usage_start_date" AS TIMESTAMP) >= date_trunc(\'month\', current_timestamp) '
        'AND CAST("line_item_usage_start_date" AS TIMESTAMP) < current_timestamp'
    )
    command["query"] = query
    try:
        client = boto3.client(
            "athena",
            region_name=AWS_REGION,
            config=Config(
                connect_timeout=COMMAND_COLLECTOR_TIMEOUT_SECONDS,
                read_timeout=COMMAND_COLLECTOR_TIMEOUT_SECONDS,
                retries={"max_attempts": 1},
            ),
        )
        response = client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": FINOPS_ATHENA_DATABASE},
            WorkGroup=FINOPS_ATHENA_WORKGROUP,
        )
        query_id = response["QueryExecutionId"]
        command["query_execution_id"] = query_id
        deadline = time.monotonic() + FINOPS_ATHENA_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            execution = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
            state = execution["Status"]["State"]
            if state == "SUCCEEDED":
                rows = client.get_query_results(QueryExecutionId=query_id, MaxResults=2)["ResultSet"]["Rows"]
                value = rows[1]["Data"][0].get("VarCharValue") if len(rows) > 1 else None
                amount = float(value) if value not in {None, ""} else 0.0
                command["status"] = "ok"
                return _athena_result(command, amount)
            if state in {"FAILED", "CANCELLED"}:
                command["status"] = state.lower()
                command["error"] = execution["Status"].get("StateChangeReason", state)
                return _athena_result(command)
            time.sleep(0.5)
        client.stop_query_execution(QueryExecutionId=query_id)
        command["status"] = "timeout"
        command["error"] = f"Athena query exceeded {FINOPS_ATHENA_TIMEOUT_SECONDS:g}s"
    except Exception as exc:
        command["error"] = str(exc)
    return _athena_result(command)


def _athena_result(command: dict[str, Any], amount: float | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "live": {
            "aws": {
                "collected_at": utcnow(),
                "region": AWS_REGION,
                "commands": {"athena_cur_mtd": command},
            }
        }
    }
    if amount is not None:
        result["cost_source"] = {
            "cur_month_to_date_usd": amount,
            "cost_explorer_month_to_date_usd": amount,
            "cost_source_type": "aws_cur_athena",
        }
    return result


def merge_present(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if value is not None:
            target[key] = value


def read_agent_source_tables(event_id: str, agent_key: str) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    try:
        with connect() as conn:
            if agent_key in {"business_control", "demand_shaping"}:
                row = conn.execute(
                    """
                    select event_id, push_channel, vip_audience_count, general_audience_count,
                           campaign_importance, crm_segment, calendar_source
                    from business_source_detail
                    where event_id = %s
                    """,
                    (event_id,),
                ).fetchone()
                if row:
                    updates["business"] = {
                        "event_id": row[0],
                        "push_channel": row[1],
                        "vip_audience_count": row[2],
                        "general_audience_count": row[3],
                        "campaign_importance": row[4],
                        "crm_segment": row[5],
                        "calendar_source": row[6],
                    }
            if agent_key == "traffic_forecast":
                row = conn.execute(
                    """
                    select event_id, alb_request_count_5m, prometheus_rps, p95_latency_ms,
                           queue_depth, pod_cpu_percent, pod_memory_percent,
                           hpa_current_replicas, hpa_desired_replicas
                    from traffic_observability_signal
                    where event_id = %s
                    """,
                    (event_id,),
                ).fetchone()
                if row:
                    updates["traffic"] = {
                        "event_id": row[0],
                        "alb_request_count_5m": row[1],
                        "prometheus_rps": row[2],
                        "p95_latency_ms": row[3],
                        "queue_depth": row[4],
                        "pod_cpu_percent": row[5],
                        "pod_memory_percent": row[6],
                        "hpa_current_replicas": row[7],
                        "hpa_desired_replicas": row[8],
                    }
            if agent_key in {"bottleneck_capacity", "infra_execution"}:
                row = conn.execute(
                    """
                    select event_id, eks_deployment_replicas, nodegroup_desired, nodegroup_max,
                           rds_cpu_percent, rds_connections, rds_read_iops,
                           redis_cache_hit_ratio_percent, alb_healthy_targets,
                           alb_unhealthy_targets, nat_gateway_bytes_out_gb
                    from infra_capacity_signal
                    where event_id = %s
                    """,
                    (event_id,),
                ).fetchone()
                if row:
                    updates["infra"] = {
                        "event_id": row[0],
                        "eks_deployment_replicas": row[1],
                        "nodegroup_desired": row[2],
                        "nodegroup_max": row[3],
                        "rds_cpu_percent": row[4],
                        "rds_connections": row[5],
                        "rds_read_iops": row[6],
                        "redis_cache_hit_ratio_percent": row[7],
                        "alb_healthy_targets": row[8],
                        "alb_unhealthy_targets": row[9],
                        "nat_gateway_bytes_out_gb": float(row[10]),
                    }
            if agent_key == "cost":
                row = conn.execute(
                    """
                    select event_id, cost_explorer_month_to_date_usd, cur_projected_monthly_usd,
                           kubecost_namespace_daily_usd, cloudwatch_logs_daily_usd,
                           nat_alb_transfer_daily_usd, event_incremental_budget_usd
                    from cost_signal
                    where event_id = %s
                    """,
                    (event_id,),
                ).fetchone()
                if row:
                    updates["cost_source"] = {
                        "event_id": row[0],
                        "cost_explorer_month_to_date_usd": float(row[1]),
                        "cur_projected_monthly_usd": float(row[2]),
                        "kubecost_namespace_daily_usd": float(row[3]),
                        "cloudwatch_logs_daily_usd": float(row[4]),
                        "nat_alb_transfer_daily_usd": float(row[5]),
                        "event_incremental_budget_usd": float(row[6]),
                        "cost_explorer_source": "postgres_fixture",
                    }
            if agent_key == "policy_guardrail":
                row = conn.execute(
                    """
                    select event_id, monthly_budget_limit_usd, approval_required_over_usd,
                           forbidden_actions, allowed_actions, policy_version
                    from policy_guardrail_source
                    where event_id = %s
                    """,
                    (event_id,),
                ).fetchone()
                if row:
                    updates["policy_source"] = {
                        "event_id": row[0],
                        "monthly_budget_limit_usd": float(row[1]),
                        "approval_required_over_usd": float(row[2]),
                        "forbidden_actions": row[3],
                        "allowed_actions": row[4],
                        "policy_version": row[5],
                    }
    except psycopg.Error as exc:
        updates.setdefault("collector_errors", []).append({"source": "postgres", "error": str(exc)})
    return updates


def collect_kubernetes_for_agent(agent_key: str) -> dict[str, Any]:
    if agent_key not in {"traffic_forecast", "bottleneck_capacity", "infra_execution"}:
        return {}
    commands = {
        "hpa": [FINOPS_KUBECTL_BIN, "get", "hpa", "-n", FINOPS_NAMESPACE, "-o", "json"],
        "pods": [
            FINOPS_KUBECTL_BIN,
            "get",
            "pods",
            "-n",
            FINOPS_NAMESPACE,
            "-l",
            FINOPS_APP_LABEL,
            "-o",
            "json",
        ],
        "pod_top": [
            FINOPS_KUBECTL_BIN,
            "top",
            "pods",
            "-n",
            FINOPS_NAMESPACE,
            "-l",
            FINOPS_APP_LABEL,
            "--no-headers",
        ],
    }
    if agent_key == "bottleneck_capacity":
        commands["endpoints"] = [
            FINOPS_KUBECTL_BIN,
            "get",
            "endpoints",
            FINOPS_UI_DEPLOYMENT,
            "-n",
            FINOPS_NAMESPACE,
            "-o",
            "json",
        ]
    if agent_key == "infra_execution":
        commands["deployment"] = [
            FINOPS_KUBECTL_BIN,
            "get",
            "deployment",
            FINOPS_UI_DEPLOYMENT,
            "-n",
            FINOPS_NAMESPACE,
            "-o",
            "json",
        ]
    command_results = {name: run_readonly_command(name, command) for name, command in commands.items()}
    hpa = first_kubernetes_item(parse_command_json(command_results["hpa"]))
    hpa_status = hpa.get("status", {})
    pods_payload = parse_command_json(command_results["pods"])
    pod_items = pods_payload.get("items", []) if pods_payload else None
    ready_pods = None
    running_pods = None
    pod_count = None
    if pod_items is not None:
        ready_pods = 0
        running_pods = 0
        pod_count = len(pod_items)
        for pod in pod_items:
            if pod.get("status", {}).get("phase") == "Running":
                running_pods += 1
            container_statuses = pod.get("status", {}).get("containerStatuses", [])
            if container_statuses and all(status.get("ready") for status in container_statuses):
                ready_pods += 1
    result: dict[str, Any] = {
        "live": {
            "kubernetes": {
                "collected_at": utcnow(),
                "namespace": FINOPS_NAMESPACE,
                "commands": command_results,
            }
        }
    }
    result["traffic"] = {
        "hpa_current_replicas": hpa_status.get("currentReplicas"),
        "hpa_desired_replicas": hpa_status.get("desiredReplicas"),
        "hpa_current_cpu_utilization_percent": hpa_status.get("currentCPUUtilizationPercentage"),
        "pod_top": parse_kubectl_top_pods(command_results["pod_top"].get("stdout", ""))
        if command_results["pod_top"].get("status") == "ok"
        else {},
    }
    result["infra"] = {
        "pod_count": pod_count,
        "running_pods": running_pods,
        "ready_pods": ready_pods,
    }
    if "deployment" in command_results:
        deployment = parse_command_json(command_results["deployment"])
        deployment_spec = deployment.get("spec", {}) if deployment else {}
        deployment_status = deployment.get("status", {}) if deployment else {}
        result["infra"].update(
            {
                "eks_deployment_replicas": deployment_spec.get("replicas"),
                "deployment_ready_replicas": deployment_status.get("readyReplicas"),
                "deployment_available_replicas": deployment_status.get("availableReplicas"),
            }
        )
    if "endpoints" in command_results:
        endpoints = parse_command_json(command_results["endpoints"])
        ready_addresses = (
            sum(len(subset.get("addresses", [])) for subset in endpoints.get("subsets", []))
            if endpoints
            else None
        )
        result["infra"]["alb_healthy_targets"] = ready_addresses
    return result


def collect_aws_for_agent(agent_key: str) -> dict[str, Any]:
    if agent_key == "cost":
        return collect_athena_cost()
    commands: dict[str, list[str]] = {}
    if agent_key == "infra_execution":
        commands.update(
            {
                "spot_price_history": [
                    FINOPS_AWS_BIN,
                    "ec2",
                    "describe-spot-price-history",
                    "--region",
                    AWS_REGION,
                    "--instance-types",
                    *FINOPS_SPOT_INSTANCE_TYPES,
                    "--product-descriptions",
                    "Linux/UNIX",
                    "--max-results",
                    "10",
                    "--output",
                    "json",
                ],
                "spot_placement_score": [
                    FINOPS_AWS_BIN,
                    "ec2",
                    "get-spot-placement-scores",
                    "--region",
                    AWS_REGION,
                    "--instance-types",
                    *FINOPS_SPOT_INSTANCE_TYPES,
                    "--target-capacity",
                    "1",
                    "--single-availability-zone",
                    "--output",
                    "json",
                ],
                "instance_type_offerings": [
                    FINOPS_AWS_BIN,
                    "ec2",
                    "describe-instance-type-offerings",
                    "--region",
                    AWS_REGION,
                    "--location-type",
                    "availability-zone",
                    "--filters",
                    f"Name=instance-type,Values={','.join(FINOPS_SPOT_INSTANCE_TYPES)}",
                    "--output",
                    "json",
                ],
            }
        )
        if FINOPS_EKS_NODEGROUP_NAME:
            commands["eks_nodegroup"] = [
                FINOPS_AWS_BIN,
                "eks",
                "describe-nodegroup",
                "--region",
                AWS_REGION,
                "--cluster-name",
                FINOPS_EKS_CLUSTER_NAME,
                "--nodegroup-name",
                FINOPS_EKS_NODEGROUP_NAME,
                "--output",
                "json",
            ]
    if not commands:
        return {}
    command_results = {name: run_readonly_command(name, command) for name, command in commands.items()}
    result: dict[str, Any] = {
        "live": {
            "aws": {
                "collected_at": utcnow(),
                "region": AWS_REGION,
                "commands": command_results,
            }
        }
    }
    if agent_key == "infra_execution":
        spot_history = (parse_command_json(command_results["spot_price_history"]) or {}).get(
            "SpotPriceHistory", []
        )
        spot_scores = (parse_command_json(command_results["spot_placement_score"]) or {}).get(
            "SpotPlacementScores", []
        )
        offerings = (parse_command_json(command_results["instance_type_offerings"]) or {}).get(
            "InstanceTypeOfferings", []
        )
        nodegroup_payload = parse_command_json(command_results.get("eks_nodegroup", {})) or {}
        nodegroup = nodegroup_payload.get("nodegroup", {})
        result["infra"] = {
            "spot_instance_types": FINOPS_SPOT_INSTANCE_TYPES,
            "latest_spot_prices": [
                {
                    "instance_type": item.get("InstanceType"),
                    "availability_zone": item.get("AvailabilityZone"),
                    "spot_price_usd_per_hour": float(item["SpotPrice"])
                    if item.get("SpotPrice")
                    else None,
                    "timestamp": item.get("Timestamp"),
                }
                for item in spot_history[:5]
            ],
            "spot_placement_scores": spot_scores[:5],
            "instance_type_offering_count": len(offerings) if offerings else None,
            "eks_nodegroup_status": nodegroup.get("status"),
            "eks_nodegroup_capacity_type": nodegroup.get("capacityType"),
            "nodegroup_desired": nodegroup.get("scalingConfig", {}).get("desiredSize"),
            "nodegroup_max": nodegroup.get("scalingConfig", {}).get("maxSize"),
        }
    return result


def enrich_context_for_agent(agent_key: str, context: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(context)
    event_id = enriched.get("event", {}).get("event_id")
    if event_id:
        for section, value in read_agent_source_tables(event_id, agent_key).items():
            if section == "collector_errors":
                enriched.setdefault("collector_errors", []).extend(value)
            elif isinstance(value, dict):
                merge_present(enriched.setdefault(section, {}), value)
    for collector_result in (collect_kubernetes_for_agent(agent_key), collect_aws_for_agent(agent_key)):
        for section, value in collector_result.items():
            if section == "live":
                live = enriched.setdefault("live", {})
                for provider, provider_value in value.items():
                    live.setdefault(provider, {}).update(provider_value)
                    live.setdefault("commands", {}).update(
                        {
                            f"{provider}_{name}": command
                            for name, command in provider_value.get("commands", {}).items()
                        }
                    )
            elif isinstance(value, dict):
                merge_present(enriched.setdefault(section, {}), value)
    return enriched


@activity.defn(name="run_finops_agent")
async def run_finops_agent(
    workflow_id: str,
    agent_key: str,
    agent_name: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    if agent_key != AGENT_KEY:
        raise ValueError(f"{AGENT_NAME} cannot run agent '{agent_key}'")
    return run_finops_agent_logic(agent_key, enrich_context_for_agent(agent_key, context))


async def start_temporal_worker() -> None:
    global temporal_client
    temporal_client = await Client.connect(TEMPORAL_ADDRESS)
    worker = Worker(
        temporal_client,
        task_queue=AGENT_TASK_QUEUE,
        activities=[run_finops_agent],
    )
    await worker.run()


@app.on_event("startup")
async def startup() -> None:
    global temporal_worker_task
    temporal_worker_task = asyncio.create_task(start_temporal_worker())


@app.on_event("shutdown")
async def shutdown() -> None:
    if temporal_worker_task:
        temporal_worker_task.cancel()


def event_policy(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return context["event"], context["policy"]


def data_requests_for(agent_key: str, available_results: dict[str, Any]) -> list[dict[str, Any]]:
    requests = []
    for request in AGENT_DATA_REQUESTS.get(agent_key, []):
        source_result = available_results.get(request["source_key"], {})
        status = "available" if request["field"] in source_result else "requested"
        requests.append({**request, "status": status})
    return requests


def response(
    agent_key: str,
    result: dict[str, Any],
    message: str,
    available_results: dict[str, Any],
) -> dict[str, Any]:
    return {
        "agent": AGENT_NAME,
        "agent_key": agent_key,
        "result": result,
        "message": message,
        "data_requests": data_requests_for(agent_key, available_results),
        "confidence": AGENT_CONFIDENCE.get(agent_key, 0.75),
    }


def run_agent(agent_key: str, context: dict[str, Any], available_results: dict[str, Any]) -> dict[str, Any]:
    event, policy = event_policy(context)
    signals = context.get("signals", {})
    previous = available_results or context.get("agent_results", {})

    if agent_key == "business_control":
        result = {
            "event_id": event["event_id"],
            "grade": event["grade"],
            "target_users": event["target_users"],
            "approval_required": policy["approval_required"],
            "max_delay_minutes": policy["max_general_delay_minutes"],
        }
        message = (
            f"{event['title']} 일정을 확인했습니다. 이벤트 등급은 {event['grade']}이고, "
            f"대상자는 {event['target_users']:,}명입니다. 운영자 승인은 필요합니다."
        )
    elif agent_key == "demand_shaping":
        business_control = previous.get("business_control", {})
        delay = business_control.get("max_delay_minutes", policy["max_general_delay_minutes"])
        vip_audience_count = business_control.get("vip_audience_count", context.get("business", {}).get("vip_audience_count"))
        general_audience_count = business_control.get(
            "general_audience_count",
            context.get("business", {}).get("general_audience_count"),
        )
        peak_reduction_percent = min(60, max(10, int(delay * 4.2)))
        result = {
            "vip": "immediate" if policy["vip_immediate"] else "batched",
            "general_users": f"spread_over_{delay}m",
            "vip_send_mode": "immediate" if policy["vip_immediate"] else "batched",
            "general_send_mode": "spread",
            "send_window_minutes": delay,
            "peak_reduction_percent": peak_reduction_percent,
            "vip_audience_count": vip_audience_count,
            "general_audience_count": general_audience_count,
        }
        message = (
            f"Business Control Agent가 준 허용 지연 시간 {delay}분을 사용하겠습니다. "
            "VIP는 즉시 발송하고 일반 사용자는 분산해서 예상 peak를 42% 낮추겠습니다."
        )
    elif agent_key == "traffic_forecast":
        shaping = previous["demand_shaping"]
        before = signals.get("baseline_peak_rps", 1420)
        send_window_minutes = shaping.get("send_window_minutes", policy["max_general_delay_minutes"])
        reduction_percent = shaping.get(
            "peak_reduction_percent",
            min(60, max(10, int(send_window_minutes * 4.2))),
        )
        after = max(1, int(before * (100 - reduction_percent) / 100))
        pods = signals.get("required_app_pods", 29)
        result = {
            "peak_rps_before": before,
            "peak_rps_after": after,
            "required_app_pods": pods,
            "based_on": "demand_shaping",
            "send_window_minutes": send_window_minutes,
            "peak_reduction_percent": reduction_percent,
            "vip_send_mode": shaping.get("vip_send_mode"),
            "general_send_mode": shaping.get("general_send_mode"),
        }
        message = (
            f"Demand Shaping Agent의 감소율 {shaping['peak_reduction_percent']}%를 반영했습니다. "
            f"평탄화 전 peak는 {before} rps, 평탄화 후 peak는 {after} rps이고 app pod는 {pods}개가 필요합니다."
        )
    elif agent_key == "bottleneck_capacity":
        forecast = previous["traffic_forecast"]
        db_cpu = signals.get("db_cpu_percent", 68)
        cache_hit_ratio = signals.get("cache_hit_ratio_percent", 91)
        result = {
            "db_cpu": f"{db_cpu}%",
            "cache_hit_ratio": f"{cache_hit_ratio}%",
            "alb_status": signals.get("alb_status", "ok"),
            "status": "warning" if db_cpu >= 65 or cache_hit_ratio < 93 else "ok",
            "validated_rps": forecast["peak_rps_after"],
        }
        message = (
            f"{forecast['peak_rps_after']} rps 기준으로 병목을 검증했습니다. "
            f"DB CPU는 {db_cpu}%, cache hit ratio는 {cache_hit_ratio}%라서 경고 수준이지만 실행은 가능합니다."
        )
    elif agent_key == "cost":
        forecast = previous["traffic_forecast"]
        eks = float(signals.get("eks_cost_usd", 31.2))
        network = float(signals.get("network_cost_usd", 8.1))
        logs = float(signals.get("log_cost_usd", 3.4))
        push = float(signals.get("push_cost_usd", 7.6))
        total = round(eks + network + logs + push, 2)
        result = {
            "eks": eks,
            "network": network,
            "logs": logs,
            "push": push,
            "total": total,
            "pod_count": forecast["required_app_pods"],
        }
        message = (
            f"app pod {forecast['required_app_pods']}개 기준으로 예상 이벤트 비용은 총 ${total}입니다. "
            f"EKS ${eks}, 네트워크 ${network}, 로그 ${logs}, push ${push}를 포함합니다."
        )
    elif agent_key == "policy_guardrail":
        result = {
            "allowed": ["scale_out", "prewarm", "spread_push"],
            "approval_required": policy["approval_required"],
        }
        message = (
            "정책상 scale-out, pre-warm, push 분산은 허용됩니다. "
            "S등급 이벤트이므로 실제 실행 전 운영자 승인이 필요합니다."
        )
    else:
        result = {"status": "skipped", "agent_key": agent_key}
        message = f"{AGENT_NAME}는 아직 별도 pod 로직이 없어 orchestrator 내부 fallback 결과를 사용합니다."

    return response(agent_key, result, message, previous)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "agent": AGENT_NAME,
        "agent_key": AGENT_KEY,
        "task_queue": AGENT_TASK_QUEUE,
    }


@app.post("/run")
def run(request: AgentRequest) -> dict[str, Any]:
    return run_finops_agent_logic(AGENT_KEY, enrich_context_for_agent(AGENT_KEY, request.context))
