import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
import boto3
from datetime import datetime, timezone
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.agent_runtime import (
    AGENT_DATA_REQUESTS,
    AGENT_SEQUENCE,
    agents_before,
    build_final_plan,
    build_replan_context,
    plan_status,
)
from app.chat_runtime import (
    build_pending_replan_response,
    run_conversation_briefing_llm,
    run_explain_llm,
    run_planner_llm,
    run_report_chat,
)
from app.dev_workflow_support import (
    TEST_EVENT_SEEDS,
    event_row_to_dict,
    merge_agent_decision_rows,
    normalize_broker_call_log,
    retry_response,
)
from app.execution_runtime import (
    build_execution_steps,
    simulate_step,
    utcnow as execution_utcnow,
    validate_execution_preconditions,
)
from app.execution_workflows import EventExecutionWorkflow
from app.workflows import FinOpsEventWorkflow
from contracts.models import ExecutionMode, ExecutionPlan, ExecutionStep, AgentResponse, ReplanIntent

FINOPS_SLACK_OUTBOUND_QUEUE_URL = os.getenv("FINOPS_SLACK_OUTBOUND_QUEUE_URL", "")
FINOPS_SLACK_CHANNEL_ID = os.getenv("FINOPS_SLACK_CHANNEL_ID", "")
FINOPS_SLACK_REPORT_ENABLED = os.getenv("FINOPS_SLACK_REPORT_ENABLED", "true").lower() == "true"
DB_HOST = os.getenv("DB_HOST", "finops-db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "finops")
DB_USER = os.getenv("DB_USER", "finops")
DB_PASSWORD = os.getenv("DB_PASSWORD", "finops")
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "finops-temporal.finops-mas.svc.cluster.local:7233")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "finops-agent-task-queue")
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
AGENT_DISPLAY_NAMES = dict(AGENT_SEQUENCE)
AGENT_DEPLOYMENTS = {
    key: f"finops-{key.replace('_', '-')}-agent"
    for key, _ in AGENT_SEQUENCE
}
DATA_REQUEST_LABELS = {
    "allowed delay": "일반 사용자 발송 허용 지연 시간",
    "peak reduction": "Push 분산에 따른 피크 감소율",
    "target audience": "이벤트 대상자 정보",
    "forecast RPS": "예상 peak RPS",
    "required pods": "필요 Pod 수",
    "target pods": "목표 Pod 수",
    "estimated cost": "예상 비용",
    "cost-to-value ratio": "비즈니스 가치 대비 비용 비율",
    "forecast baseline": "사후 비교용 예측 기준",
    "forecast cost": "사후 비교용 예측 비용",
}

app = FastAPI(title="FinOps Orchestrator", version="0.4.0")
temporal_client: Client | None = None
temporal_worker_task: asyncio.Task | None = None
AGENT_STEP_DELAY_SECONDS = float(os.getenv("AGENT_STEP_DELAY_SECONDS", "0.8"))

class ChatRequest(BaseModel):
    workflow_id: str | None = None
    message: str
    conversation_history: list[dict[str, Any]] = []


class ApprovalRequest(BaseModel):
    approved_by: str = "operator"
    decision: str = "approved"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect():
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        autocommit=True,
    )


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


def agent_display_name(value: str | None) -> str:
    if not value:
        return "Agent"
    return AGENT_DISPLAY_NAMES.get(value, value)


def readable_data_label(label: str | None, field: str | None = None) -> str:
    if label and label in DATA_REQUEST_LABELS:
        return DATA_REQUEST_LABELS[label]
    if field:
        return field.replace("_", " ")
    return label or "필요한 값"


def dialogue_from_payload(
    sender: str,
    receiver: str,
    message: str,
    payload: Any,
) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {"sender": sender, "receiver": receiver, "message": message}

    payload_type = payload.get("type")
    if payload_type in {"data_request", "value_request"}:
        requester = payload.get("requester_name") or agent_display_name(payload.get("requester_agent")) or sender
        source = payload.get("source_name") or agent_display_name(payload.get("source_agent")) or receiver
        label = readable_data_label(payload.get("label"), payload.get("field"))
        return {
            "sender": requester,
            "receiver": source,
            "message": f"{label}을 알려줘. 이 값으로 다음 계산을 진행할게.",
        }

    if payload_type == "value_response":
        source = payload.get("source_name") or agent_display_name(payload.get("source_agent")) or sender
        requester = payload.get("requester_name") or agent_display_name(payload.get("requester_agent")) or receiver
        label = readable_data_label(payload.get("label"), payload.get("field"))
        return {
            "sender": source,
            "receiver": requester,
            "message": f"{label} 값은 {format_agent_value(payload.get('value'))}입니다. 이 값을 기준으로 진행하세요.",
        }

    if payload_type == "broker_data_request":
        requester = agent_display_name(payload.get("requester_agent")) or sender
        target = agent_display_name(payload.get("target_agent")) or receiver
        operation = str(payload.get("operation") or "필요한 작업").replace("_", " ")
        fields = ", ".join(payload.get("required_fields") or [])
        suffix = f" 필요한 값은 {fields}입니다." if fields else ""
        return {
            "sender": requester,
            "receiver": target,
            "message": f"{operation} 작업을 진행할 수 있게 확인해줘.{suffix}",
        }

    return {"sender": sender, "receiver": receiver, "message": message}


def summarize_agent_completion(agent: str, result: Any, fallback: str) -> str:
    payload = result if isinstance(result, dict) else {}
    nested = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if not isinstance(nested, dict):
        return fallback

    if agent == "Cluster State Agent":
        return (
            f"현재 클러스터를 확인했습니다. 전체 replica는 {nested.get('total_cluster_pods', '-')}개, "
            f"이벤트 관련 Pod는 {nested.get('total_event_related_pods', '-')}개, "
            f"유휴 후보는 {nested.get('idle_candidate_count', 0)}개입니다."
        )
    if agent == "Business Control Agent":
        return (
            f"이벤트 조건을 정리했습니다. 등급은 {nested.get('grade', '-')}이고 "
            f"대상자는 {nested.get('target_users', '-')}명입니다. "
            f"일반 사용자는 최대 {nested.get('max_delay_minutes', '-')}분까지 분산 가능합니다."
        )
    if agent == "Demand Shaping Agent":
        return (
            f"발송 분산 전략을 만들었습니다. 일반 사용자 {nested.get('general_count', '-')}명을 "
            f"{nested.get('send_window_minutes', '-')}분 동안 분산해 초당 약 "
            f"{nested.get('per_second_general', '-')}명씩 발송합니다."
        )
    if agent == "Traffic Forecast Agent":
        return (
            f"트래픽을 예측했습니다. 예상 peak RPS는 {nested.get('peak_rps_after', '-')}이고 "
            f"필요한 App Pod는 {nested.get('required_app_pods', '-')}개입니다."
        )
    if agent == "Bottleneck Capacity Agent":
        return (
            f"병목을 검증했습니다. DB 위험도는 {nested.get('db_risk', nested.get('status', '-'))}, "
            f"Pod 준비율은 {nested.get('pod_readiness_percent', '-')}입니다."
        )
    if agent == "Infra Capacity Planning Agent":
        return (
            f"인프라 용량 계획을 만들었습니다. 현재 {nested.get('current_app_pods', '-')}개에서 "
            f"목표 {nested.get('target_app_pods', '-')}개로, "
            f"추가 {nested.get('scale_out_pods', '-')}개 증설이 필요합니다."
        )
    if agent == "Cost Agent":
        return (
            f"비용을 계산했습니다. 예상 총비용은 ${nested.get('total', nested.get('estimated_cost_usd', '-'))}이고 "
            f"유휴 자원 절감액은 ${nested.get('idle_saving_usd', nested.get('idle_resource_saving_usd', '-'))}입니다."
        )
    if agent == "Unit Economics Agent":
        return (
            f"경제성을 검토했습니다. 비용 비율은 {nested.get('cost_ratio', '-')}이고 "
            f"최종 권고는 {nested.get('final_approval_recommendation', nested.get('approval_recommendation', '-'))}입니다."
        )
    if agent == "Policy & Fallback Guardrail Agent":
        return "정책과 비상 대응 계획을 확인했습니다. 허용/금지 액션과 fallback 계획을 보고서에 반영했습니다."
    if agent == "Postmortem Learning Agent":
        return (
            f"사후 학습 기준을 준비했습니다. 예측 peak RPS는 {nested.get('forecast_peak_rps', '-')}이고 "
            f"예측 비용은 ${nested.get('forecast_cost_usd', '-')}입니다."
        )
    return fallback


def conversation_row_to_dialogue(row: tuple[Any, ...]) -> dict[str, Any]:
    phase, sender, receiver, message, payload, created_at = row
    dialogue = dialogue_from_payload(sender, receiver, message, payload)
    if sender != "Temporal Data Broker" and isinstance(payload, dict) and payload.get("result"):
        dialogue["message"] = summarize_agent_completion(sender, payload, dialogue["message"])
    return {
        "phase": phase,
        "sender": dialogue["sender"],
        "receiver": dialogue["receiver"],
        "message": dialogue["message"],
        "payload": payload,
        "created_at": created_at,
    }


def parse_kubectl_top_pods(stdout: str) -> dict[str, Any]:
    pods = []
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] != "NAME":
            pods.append({"name": parts[0], "cpu": parts[1], "memory": parts[2]})
    return {"pods": pods, "sample_count": len(pods)}


def collect_kubernetes_live_context() -> dict[str, Any]:
    commands = {
        "deployment": [
            FINOPS_KUBECTL_BIN,
            "get",
            "deployment",
            FINOPS_UI_DEPLOYMENT,
            "-n",
            FINOPS_NAMESPACE,
            "-o",
            "json",
        ],
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
        "endpoints": [
            FINOPS_KUBECTL_BIN,
            "get",
            "endpoints",
            FINOPS_UI_DEPLOYMENT,
            "-n",
            FINOPS_NAMESPACE,
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
    command_results = {name: run_readonly_command(name, command) for name, command in commands.items()}
    deployment = parse_command_json(command_results["deployment"])
    hpa_payload = parse_command_json(command_results["hpa"])
    pods_payload = parse_command_json(command_results["pods"])
    endpoints = parse_command_json(command_results["endpoints"])
    top_result = command_results["pod_top"]

    deployment_status = deployment.get("status", {}) if deployment else {}
    deployment_spec = deployment.get("spec", {}) if deployment else {}
    hpa = first_kubernetes_item(hpa_payload)
    hpa_status = hpa.get("status", {})
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

    ready_addresses = None
    if endpoints:
        ready_addresses = 0
        for subset in endpoints.get("subsets", []):
            ready_addresses += len(subset.get("addresses", []))

    return {
        "collected_at": utcnow(),
        "namespace": FINOPS_NAMESPACE,
        "commands": command_results,
        "traffic": {
            "hpa_current_replicas": hpa_status.get("currentReplicas"),
            "hpa_desired_replicas": hpa_status.get("desiredReplicas"),
            "hpa_current_cpu_utilization_percent": hpa_status.get("currentCPUUtilizationPercentage"),
            "pod_top": parse_kubectl_top_pods(top_result.get("stdout", "")) if top_result.get("status") == "ok" else {},
        },
        "infra": {
            "eks_deployment_replicas": deployment_spec.get("replicas"),
            "deployment_ready_replicas": deployment_status.get("readyReplicas"),
            "deployment_available_replicas": deployment_status.get("availableReplicas"),
            "pod_count": pod_count,
            "running_pods": running_pods,
            "ready_pods": ready_pods,
            "alb_healthy_targets": ready_addresses,
        },
    }


def pod_waiting_reason(pod: dict[str, Any]) -> str | None:
    for status in pod.get("status", {}).get("containerStatuses", []) or []:
        waiting = status.get("state", {}).get("waiting")
        if waiting:
            return waiting.get("reason") or waiting.get("message")
    return None


def runtime_status(desired: int, ready: int, pod_items: list[dict[str, Any]]) -> tuple[str, str]:
    reasons = [pod_waiting_reason(pod) for pod in pod_items]
    reasons = [reason for reason in reasons if reason]
    if reasons:
        return "Error", ", ".join(sorted(set(reasons)))
    if desired == 0:
        return "Sleeping", "replica가 0이라 대기 중입니다."
    if ready >= desired:
        return "Running", "필요한 replica가 Ready 상태입니다."
    if pod_items:
        phases = sorted(set(pod.get("status", {}).get("phase", "Unknown") for pod in pod_items))
        return "Starting", f"Pod 상태: {', '.join(phases)}"
    return "Starting", "Deployment는 켜졌지만 아직 Pod가 생성되지 않았습니다."


def collect_agent_runtime_status() -> list[dict[str, Any]]:
    deployments_result = run_readonly_command(
        "agent_deployments",
        [
            FINOPS_KUBECTL_BIN,
            "get",
            "deploy",
            "-n",
            FINOPS_NAMESPACE,
            "-l",
            FINOPS_APP_LABEL,
            "-o",
            "json",
        ],
    )
    pods_result = run_readonly_command(
        "agent_pods",
        [
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
    )
    deployment_payload = parse_command_json(deployments_result)
    pod_payload = parse_command_json(pods_result)
    deployments = {
        item.get("metadata", {}).get("name"): item
        for item in (deployment_payload or {}).get("items", [])
        if isinstance(item, dict)
    }
    pods_by_app: dict[str, list[dict[str, Any]]] = {}
    for pod in (pod_payload or {}).get("items", []):
        labels = pod.get("metadata", {}).get("labels", {})
        app_name = labels.get("app.kubernetes.io/name") or labels.get("app")
        if app_name:
            pods_by_app.setdefault(app_name, []).append(pod)

    statuses = []
    for agent_key, agent_name in AGENT_SEQUENCE:
        deployment_name = AGENT_DEPLOYMENTS[agent_key]
        deployment = deployments.get(deployment_name, {})
        spec = deployment.get("spec", {})
        deployment_status = deployment.get("status", {})
        containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        pod_items = pods_by_app.get(deployment_name, [])
        desired = int(spec.get("replicas") or 0)
        ready = int(deployment_status.get("readyReplicas") or 0)
        state, reason = runtime_status(desired, ready, pod_items)
        restart_count = 0
        pod_names = []
        pod_phases = []
        for pod in pod_items:
            pod_names.append(pod.get("metadata", {}).get("name"))
            pod_phases.append(pod.get("status", {}).get("phase"))
            for container_status in pod.get("status", {}).get("containerStatuses", []) or []:
                restart_count += int(container_status.get("restartCount") or 0)
        statuses.append(
            {
                "agent_key": agent_key,
                "agent_name": agent_name,
                "deployment": deployment_name,
                "desired_replicas": desired,
                "ready_replicas": ready,
                "available_replicas": int(deployment_status.get("availableReplicas") or 0),
                "status": state,
                "reason": reason,
                "image": containers[0].get("image") if containers else None,
                "pod_names": [name for name in pod_names if name],
                "pod_phases": [phase for phase in pod_phases if phase],
                "restart_count": restart_count,
            }
        )
    return statuses


def collect_aws_live_context() -> dict[str, Any]:
    commands = {
        "identity": [
            FINOPS_AWS_BIN,
            "sts",
            "get-caller-identity",
            "--region",
            AWS_REGION,
            "--output",
            "json",
        ],
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

    command_results = {name: run_readonly_command(name, command) for name, command in commands.items()}
    spot_history = (parse_command_json(command_results["spot_price_history"]) or {}).get("SpotPriceHistory", [])
    spot_scores = (parse_command_json(command_results["spot_placement_score"]) or {}).get("SpotPlacementScores", [])
    offerings = (parse_command_json(command_results["instance_type_offerings"]) or {}).get("InstanceTypeOfferings", [])
    nodegroup_payload = parse_command_json(command_results.get("eks_nodegroup", {})) or {}

    latest_spot_prices = []
    for item in spot_history[:5]:
        latest_spot_prices.append(
            {
                "instance_type": item.get("InstanceType"),
                "availability_zone": item.get("AvailabilityZone"),
                "spot_price_usd_per_hour": float(item["SpotPrice"]) if item.get("SpotPrice") else None,
                "timestamp": item.get("Timestamp"),
            }
        )

    nodegroup = nodegroup_payload.get("nodegroup", {})
    return {
        "collected_at": utcnow(),
        "region": AWS_REGION,
        "commands": command_results,
        "infra": {
            "spot_instance_types": FINOPS_SPOT_INSTANCE_TYPES,
            "latest_spot_prices": latest_spot_prices,
            "spot_placement_scores": spot_scores[:5],
            "instance_type_offering_count": len(offerings),
            "eks_nodegroup_status": nodegroup.get("status"),
            "eks_nodegroup_capacity_type": nodegroup.get("capacityType"),
            "eks_nodegroup_desired": nodegroup.get("scalingConfig", {}).get("desiredSize"),
            "eks_nodegroup_max": nodegroup.get("scalingConfig", {}).get("maxSize"),
        },
    }


def format_agent_value(value: Any) -> str:
    if isinstance(value, bool):
        return "필요함" if value else "필요하지 않음"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def build_agent_value_exchange(
    agent_key: str,
    agent_name: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    messages = []
    agent_results = context.get("agent_results", {})
    for request in AGENT_DATA_REQUESTS.get(agent_key, []):
        source_key = request["source_key"]
        source_response = agent_results.get(source_key)
        source_result = (
            AgentResponse.model_validate(source_response).result
            if source_response is not None
            else None
        )
        if source_result is None or request["field"] not in source_result:
            continue
        value = source_result[request["field"]]
        data_request = {
            "requester_agent": agent_key,
            "requester_name": agent_name,
            "source_agent": source_key,
            "source_name": request["source_name"],
            "field": request["field"],
            "label": request["label"],
            "reason": request.get("reason", ""),
            "status": "fulfilled_from_workflow_state",
            "value": value,
        }
        context.setdefault("data_requests", []).append(data_request)
        messages.append(
            {
                "sender": agent_name,
                "receiver": "Temporal Data Broker",
                "message": (
                    f"{request['label']} 값이 필요합니다. "
                    f"이유: {request.get('reason', '다음 판단에 필요한 입력값입니다.')}"
                ),
                "payload": {"type": "value_request", **data_request, "value": None},
            }
        )
        messages.append(
            {
                "sender": "Temporal Data Broker",
                "receiver": agent_name,
                "message": (
                    f"{request['source_name']}가 이미 만든 {request['label']} 값은 "
                    f"{format_agent_value(value)}입니다. 이 값을 사용해서 계속 진행하세요."
                ),
                "payload": {"type": "value_response", **data_request},
            }
        )
    return messages


def normalize_agent_output(
    agent_key: str,
    agent_name: str,
    output: dict[str, Any],
) -> AgentResponse:
    response = AgentResponse.model_validate(output)
    if response.agent_key != agent_key:
        raise ValueError(
            f"expected response from {agent_key}, received {response.agent_key}"
        )
    accepted_agent_names = {agent_name}
    if agent_key == "infra_execution":
        accepted_agent_names.update(
            {
                "Infra Execution Planner",
                "Infra Capacity Planning Agent",
            }
        )
    if agent_key == "policy_guardrail":
        accepted_agent_names.update(
            {
                "Policy Guardrail Agent",
                "Policy & Fallback Guardrail Agent",
            }
        )
    if response.agent_name not in accepted_agent_names:
        raise ValueError(
            f"expected agent name {agent_name}, received {response.agent_name}"
        )
    return response


def fetch_event_context(event_id: str) -> dict[str, Any]:
    with connect() as conn:
        event = conn.execute(
            """
            select event_id, title, grade, target_users, max_delay_minutes, scheduled_at
            from business_calendar
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
        policy = conn.execute(
            """
            select event_id, vip_immediate, approval_required, max_general_delay_minutes
            from business_policy
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
        signals = conn.execute(
            """
            select
              event_id,
              baseline_peak_rps,
              shaped_peak_rps,
              required_app_pods,
              db_cpu_percent,
              cache_hit_ratio_percent,
              alb_status,
              eks_cost_usd,
              network_cost_usd,
              log_cost_usd,
              push_cost_usd,
              expected_value_usd,
              scale_down_rps_threshold
            from event_mock_signal
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
        business_source = conn.execute(
            """
            select
              event_id,
              push_channel,
              vip_audience_count,
              general_audience_count,
              campaign_importance,
              crm_segment,
              calendar_source
            from business_source_detail
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
        traffic_source = conn.execute(
            """
            select
              event_id,
              alb_request_count_5m,
              prometheus_rps,
              p95_latency_ms,
              queue_depth,
              pod_cpu_percent,
              pod_memory_percent,
              hpa_current_replicas,
              hpa_desired_replicas
            from traffic_observability_signal
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
        infra_source = conn.execute(
            """
            select
              event_id,
              eks_deployment_replicas,
              nodegroup_desired,
              nodegroup_max,
              rds_cpu_percent,
              rds_connections,
              rds_read_iops,
              redis_cache_hit_ratio_percent,
              alb_healthy_targets,
              alb_unhealthy_targets,
              nat_gateway_bytes_out_gb
            from infra_capacity_signal
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
        cost_source = conn.execute(
            """
            select
              event_id,
              cost_explorer_month_to_date_usd,
              cur_projected_monthly_usd,
              kubecost_namespace_daily_usd,
              cloudwatch_logs_daily_usd,
              nat_alb_transfer_daily_usd,
              event_incremental_budget_usd
            from cost_signal
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
        policy_source = conn.execute(
            """
            select
              event_id,
              monthly_budget_limit_usd,
              approval_required_over_usd,
              forbidden_actions,
              allowed_actions,
              policy_version
            from policy_guardrail_source
            where event_id = %s
            """,
            (event_id,),
        ).fetchone()
        history_rows = conn.execute(
            """
            select event_date, event_name,
                   actual_peak_rps, actual_shaped_rps,
                   actual_pods_used, actual_cost_usd,
                   actual_p95_ms
            from event_history
            where event_type = %s
            order by event_date desc
            limit 5
            """,
            (_event_history_type(event_id),),
        ).fetchall()
    if not event or not policy or not signals:
        raise ValueError(f"event context not found: {event_id}")
    business = {
        "event_id": business_source[0],
        "push_channel": business_source[1],
        "vip_audience_count": business_source[2],
        "general_audience_count": business_source[3],
        "campaign_importance": business_source[4],
        "crm_segment": business_source[5],
        "calendar_source": business_source[6],
    } if business_source else {}
    traffic = {
        "event_id": traffic_source[0],
        "alb_request_count_5m": traffic_source[1],
        "prometheus_rps": traffic_source[2],
        "p95_latency_ms": traffic_source[3],
        "queue_depth": traffic_source[4],
        "pod_cpu_percent": traffic_source[5],
        "pod_memory_percent": traffic_source[6],
        "hpa_current_replicas": traffic_source[7],
        "hpa_desired_replicas": traffic_source[8],
    } if traffic_source else {}
    infra = {
        "event_id": infra_source[0],
        "eks_deployment_replicas": infra_source[1],
        "nodegroup_desired": infra_source[2],
        "nodegroup_max": infra_source[3],
        "rds_cpu_percent": infra_source[4],
        "rds_connections": infra_source[5],
        "rds_read_iops": infra_source[6],
        "redis_cache_hit_ratio_percent": infra_source[7],
        "alb_healthy_targets": infra_source[8],
        "alb_unhealthy_targets": infra_source[9],
        "nat_gateway_bytes_out_gb": float(infra_source[10]),
    } if infra_source else {}
    cost = {
        "event_id": cost_source[0],
        "cost_explorer_month_to_date_usd": float(cost_source[1]),
        "cur_projected_monthly_usd": float(cost_source[2]),
        "kubecost_namespace_daily_usd": float(cost_source[3]),
        "cloudwatch_logs_daily_usd": float(cost_source[4]),
        "nat_alb_transfer_daily_usd": float(cost_source[5]),
        "event_incremental_budget_usd": float(cost_source[6]),
    } if cost_source else {}
    policy_detail = {
        "event_id": policy_source[0],
        "monthly_budget_limit_usd": float(policy_source[1]),
        "approval_required_over_usd": float(policy_source[2]),
        "forbidden_actions": policy_source[3],
        "allowed_actions": policy_source[4],
        "policy_version": policy_source[5],
    } if policy_source else {}
    event_history = [
        {
            "event_date": str(row[0]),
            "event_name": row[1],
            "actual_peak_rps": row[2],
            "actual_shaped_rps": row[3],
            "actual_pods_used": row[4],
            "actual_cost_usd": float(row[5]),
            "actual_p95_ms": row[6],
        }
        for row in history_rows
    ]
    return {
        "event": {
            "event_id": event[0],
            "title": event[1],
            "grade": event[2],
            "target_users": event[3],
            "max_delay_minutes": event[4],
            "scheduled_at": event[5],
        },
        "policy": {
            "event_id": policy[0],
            "vip_immediate": policy[1],
            "approval_required": policy[2],
            "max_general_delay_minutes": policy[3],
        },
        "signals": {
            "event_id": signals[0],
            "baseline_peak_rps": signals[1],
            "shaped_peak_rps": signals[2],
            "required_app_pods": signals[3],
            "db_cpu_percent": signals[4],
            "cache_hit_ratio_percent": signals[5],
            "alb_status": signals[6],
            "eks_cost_usd": float(signals[7]),
            "network_cost_usd": float(signals[8]),
            "log_cost_usd": float(signals[9]),
            "push_cost_usd": float(signals[10]),
            "expected_value_usd": float(signals[11]),
            "scale_down_rps_threshold": signals[12],
        },
        "business": business,
        "traffic": traffic,
        "infra": infra,
        "cost_source": cost,
        "policy_source": policy_detail,
        "event_history": event_history,
        "live": {},
        "agent_results": {},
    }


def _event_history_type(event_id: str) -> str:
    if "fomc" in event_id:
        return "fomc"
    return event_id


def enrich_local_agent_context(agent_key: str, context: dict[str, Any]) -> dict[str, Any]:
    if agent_key != "infra_execution":
        return context
    enriched = dict(context)
    kubernetes_live = collect_kubernetes_live_context()
    aws_live = collect_aws_live_context()
    live = enriched.setdefault("live", {})
    live["kubernetes"] = kubernetes_live
    live["aws"] = aws_live
    live.setdefault("commands", {}).update(kubernetes_live.get("commands", {}))
    live.setdefault("commands", {}).update(
        {f"aws_{key}": value for key, value in aws_live.get("commands", {}).items()}
    )
    for key, value in kubernetes_live.get("infra", {}).items():
        if value is not None:
            enriched.setdefault("infra", {})[key] = value
    for key, value in aws_live.get("infra", {}).items():
        if value is not None:
            enriched.setdefault("infra", {})[key] = value
    return enriched


def init_db() -> None:
    for _ in range(20):
        try:
            with connect() as conn:
                conn.execute(
                    """
                    create table if not exists business_calendar (
                      event_id text primary key,
                      title text not null,
                      grade text not null,
                      target_users integer not null,
                      max_delay_minutes integer not null,
                      scheduled_at text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists business_policy (
                      event_id text primary key,
                      vip_immediate boolean not null,
                      approval_required boolean not null,
                      max_general_delay_minutes integer not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists event_mock_signal (
                      event_id text primary key,
                      baseline_peak_rps integer not null,
                      shaped_peak_rps integer not null,
                      required_app_pods integer not null,
                      db_cpu_percent integer not null,
                      cache_hit_ratio_percent integer not null,
                      alb_status text not null,
                      eks_cost_usd numeric not null,
                      network_cost_usd numeric not null,
                      log_cost_usd numeric not null,
                      push_cost_usd numeric not null,
                      expected_value_usd numeric not null,
                      scale_down_rps_threshold integer not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists business_source_detail (
                      event_id text primary key,
                      push_channel text not null,
                      vip_audience_count integer not null,
                      general_audience_count integer not null,
                      campaign_importance text not null,
                      crm_segment text not null,
                      calendar_source text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists traffic_observability_signal (
                      event_id text primary key,
                      alb_request_count_5m integer not null,
                      prometheus_rps integer not null,
                      p95_latency_ms integer not null,
                      queue_depth integer not null,
                      pod_cpu_percent integer not null,
                      pod_memory_percent integer not null,
                      hpa_current_replicas integer not null,
                      hpa_desired_replicas integer not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists infra_capacity_signal (
                      event_id text primary key,
                      eks_deployment_replicas integer not null,
                      nodegroup_desired integer not null,
                      nodegroup_max integer not null,
                      rds_cpu_percent integer not null,
                      rds_connections integer not null,
                      rds_read_iops integer not null,
                      redis_cache_hit_ratio_percent integer not null,
                      alb_healthy_targets integer not null,
                      alb_unhealthy_targets integer not null,
                      nat_gateway_bytes_out_gb numeric not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists cost_signal (
                      event_id text primary key,
                      cost_explorer_month_to_date_usd numeric not null,
                      cur_projected_monthly_usd numeric not null,
                      kubecost_namespace_daily_usd numeric not null,
                      cloudwatch_logs_daily_usd numeric not null,
                      nat_alb_transfer_daily_usd numeric not null,
                      event_incremental_budget_usd numeric not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists policy_guardrail_source (
                      event_id text primary key,
                      monthly_budget_limit_usd numeric not null,
                      approval_required_over_usd numeric not null,
                      forbidden_actions jsonb not null,
                      allowed_actions jsonb not null,
                      policy_version text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists event_history (
                      id serial primary key,
                      event_type varchar(50),
                      event_date date,
                      event_name varchar(200),
                      target_users integer,
                      grade varchar(10),
                      actual_peak_rps integer,
                      actual_shaped_rps integer,
                      actual_pods_used integer,
                      actual_cost_usd numeric(10,2),
                      actual_p95_ms integer,
                      actual_duration_minutes integer,
                      demand_shaping_window_minutes integer,
                      peak_reduction_percent integer,
                      created_at timestamptz default now(),
                      unique (event_type, event_date, event_name)
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists cluster_resource_snapshot (
                      id serial primary key,
                      workflow_id varchar(50),
                      namespace varchar(100),
                      deployment_name varchar(200),
                      current_replicas integer,
                      ready_replicas integer,
                      hpa_min integer,
                      hpa_max integer,
                      reducible_replicas integer default 0,
                      estimated_saving_usd numeric(10,2) default 0,
                      created_at timestamptz default now()
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists agent_decision_log (
                      id serial primary key,
                      workflow_id text not null,
                      phase integer not null,
                      agent text not null,
                      status text not null,
                      result jsonb not null,
                      created_at text not null,
                      agent_key text,
                      confidence numeric,
                      reasoning_source text,
                      evidence jsonb,
                      warnings jsonb,
                      data_requests jsonb,
                      input_context jsonb,
                      started_at text,
                      completed_at text
                    )
                    """
                )
                conn.execute(
                    """
                    alter table agent_decision_log
                      add column if not exists agent_key text,
                      add column if not exists confidence numeric,
                      add column if not exists reasoning_source text,
                      add column if not exists evidence jsonb,
                      add column if not exists warnings jsonb,
                      add column if not exists data_requests jsonb,
                      add column if not exists input_context jsonb,
                      add column if not exists started_at text,
                      add column if not exists completed_at text
                    """
                )
                conn.execute(
                    """
                    create table if not exists agent_conversation_log (
                      id serial primary key,
                      workflow_id text not null,
                      phase integer not null,
                      sender text not null,
                      receiver text not null,
                      message text not null,
                      payload jsonb not null,
                      created_at text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists final_event_plan (
                      workflow_id text primary key,
                      event_id text not null,
                      status text not null,
                      plan jsonb not null,
                      created_at text not null,
                      updated_at text not null
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists approval_request (
                      workflow_id text primary key,
                      status text not null,
                      requested_at text not null,
                      decided_at text,
                      decided_by text
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists event_execution (
                      execution_workflow_id text primary key,
                      planning_workflow_id text not null,
                      event_id text not null,
                      mode text not null default 'dry_run',
                      status text not null default 'pending',
                      execution_plan jsonb,
                      created_at text,
                      updated_at text
                    )
                    """
                )
                conn.execute(
                    """
                    create table if not exists execution_step_log (
                      id serial primary key,
                      execution_workflow_id text not null,
                      step_id text not null,
                      step_type text not null,
                      status text not null,
                      result jsonb,
                      started_at text,
                      completed_at text,
                      created_at text
                    )
                    """
                )
                seed(conn)
            return
        except psycopg.OperationalError:
            time.sleep(2)
    raise RuntimeError("database is not reachable")


def build_seed_event(definition: dict[str, Any]) -> dict[str, Any]:
    event_id = definition["event_id"]
    target_users = int(definition["target_users"])
    baseline_rps = int(definition["baseline_peak_rps"])
    traffic_rps = int(definition.get("traffic_rps", baseline_rps))
    pods = int(definition["required_app_pods"])
    rds_cpu = int(definition["rds_cpu_percent"])
    cache_hit_ratio = int(definition.get("redis_cache_hit_ratio_percent", 91))
    vip_users = max(1, int(target_users * 0.12))
    current_pods = max(1, int(pods * 0.62))
    return {
        "calendar": {
            "event_id": event_id,
            "title": definition["title"],
            "grade": definition["grade"],
            "target_users": target_users,
            "max_delay_minutes": 10,
            "scheduled_at": definition["scheduled_at"],
        },
        "policy": {
            "vip_immediate": True,
            "approval_required": True,
            "max_general_delay_minutes": 10,
        },
        "mock": {
            "baseline_peak_rps": baseline_rps,
            "shaped_peak_rps": max(1, int(baseline_rps * 0.58)),
            "required_app_pods": pods,
            "db_cpu_percent": rds_cpu,
            "cache_hit_ratio_percent": cache_hit_ratio,
            "alb_status": "ok",
            "eks_cost_usd": float(definition.get("eks_cost_usd", 31.2)),
            "network_cost_usd": float(definition.get("network_cost_usd", 8.1)),
            "log_cost_usd": float(definition.get("log_cost_usd", 3.4)),
            "push_cost_usd": float(definition.get("push_cost_usd", 7.6)),
            "expected_value_usd": max(1000.0, target_users * 0.012),
            "scale_down_rps_threshold": max(200, int(traffic_rps * 0.42)),
        },
        "business": {
            "push_channel": "mobile-push",
            "vip_audience_count": vip_users,
            "general_audience_count": target_users - vip_users,
            "campaign_importance": f"grade-{definition['grade'].lower()}",
            "crm_segment": "finops-test-segment",
            "calendar_source": "finops-test-fixture",
        },
        "traffic": {
            "alb_request_count_5m": traffic_rps * 300,
            "prometheus_rps": traffic_rps,
            "p95_latency_ms": 188 if traffic_rps < 2500 else 245,
            "queue_depth": max(100, traffic_rps * 5),
            "pod_cpu_percent": 63,
            "pod_memory_percent": 71,
            "hpa_current_replicas": current_pods,
            "hpa_desired_replicas": pods,
        },
        "infra": {
            "eks_deployment_replicas": current_pods,
            "nodegroup_desired": max(3, current_pods // 2),
            "nodegroup_max": max(30, pods + 10),
            "rds_cpu_percent": rds_cpu,
            "rds_connections": 640,
            "rds_read_iops": 12500,
            "redis_cache_hit_ratio_percent": cache_hit_ratio,
            "alb_healthy_targets": current_pods,
            "alb_unhealthy_targets": 0,
            "nat_gateway_bytes_out_gb": 37.4,
        },
        "cost": {
            "cost_explorer_month_to_date_usd": 18420.55,
            "cur_projected_monthly_usd": 28600.0,
            "kubecost_namespace_daily_usd": 73.25,
            "cloudwatch_logs_daily_usd": 11.8,
            "nat_alb_transfer_daily_usd": 15.7,
            "event_incremental_budget_usd": float(
                definition["event_incremental_budget_usd"]
            ),
        },
        "guardrail": {
            "monthly_budget_limit_usd": 30000.0,
            "approval_required_over_usd": 50.0,
            "forbidden_actions": [
                "disable_hpa",
                "scale_rds_down_during_event",
                "delete_warm_pool",
            ],
            "allowed_actions": definition.get(
                "allowed_actions",
                ["scale_out", "prewarm", "spread_push", "add_read_replica"],
            ),
            "policy_version": "finops-policy-2026.06-test",
        },
        "omit_traffic_signal": bool(definition.get("omit_traffic_signal", False)),
        "omit_cost_signal": bool(definition.get("omit_cost_signal", False)),
    }


def seed_event(conn, definition: dict[str, Any]) -> None:
    event = build_seed_event(definition)
    calendar = event["calendar"]
    conn.execute(
        """
        insert into business_calendar
          (event_id, title, grade, target_users, max_delay_minutes, scheduled_at)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (event_id) do update set
          title = excluded.title,
          grade = excluded.grade,
          target_users = excluded.target_users,
          max_delay_minutes = excluded.max_delay_minutes,
          scheduled_at = excluded.scheduled_at
        """,
        tuple(calendar.values()),
    )
    policy = event["policy"]
    conn.execute(
        """
        insert into business_policy
          (event_id, vip_immediate, approval_required, max_general_delay_minutes)
        values (%s, %s, %s, %s)
        on conflict (event_id) do nothing
        """,
        (calendar["event_id"], *policy.values()),
    )
    mock = event["mock"]
    conn.execute(
        """
        insert into event_mock_signal
          (event_id, baseline_peak_rps, shaped_peak_rps, required_app_pods,
           db_cpu_percent, cache_hit_ratio_percent, alb_status, eks_cost_usd,
           network_cost_usd, log_cost_usd, push_cost_usd, expected_value_usd,
           scale_down_rps_threshold)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (event_id) do nothing
        """,
        (calendar["event_id"], *mock.values()),
    )
    business = event["business"]
    conn.execute(
        """
        insert into business_source_detail
          (event_id, push_channel, vip_audience_count, general_audience_count,
           campaign_importance, crm_segment, calendar_source)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (event_id) do nothing
        """,
        (calendar["event_id"], *business.values()),
    )
    if not event["omit_traffic_signal"]:
        traffic = event["traffic"]
        conn.execute(
            """
            insert into traffic_observability_signal
              (event_id, alb_request_count_5m, prometheus_rps, p95_latency_ms,
               queue_depth, pod_cpu_percent, pod_memory_percent,
               hpa_current_replicas, hpa_desired_replicas)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (event_id) do nothing
            """,
            (calendar["event_id"], *traffic.values()),
        )
    infra = event["infra"]
    conn.execute(
        """
        insert into infra_capacity_signal
          (event_id, eks_deployment_replicas, nodegroup_desired, nodegroup_max,
           rds_cpu_percent, rds_connections, rds_read_iops,
           redis_cache_hit_ratio_percent, alb_healthy_targets,
           alb_unhealthy_targets, nat_gateway_bytes_out_gb)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (event_id) do nothing
        """,
        (calendar["event_id"], *infra.values()),
    )
    if not event["omit_cost_signal"]:
        cost = event["cost"]
        conn.execute(
            """
            insert into cost_signal
              (event_id, cost_explorer_month_to_date_usd,
               cur_projected_monthly_usd, kubecost_namespace_daily_usd,
               cloudwatch_logs_daily_usd, nat_alb_transfer_daily_usd,
               event_incremental_budget_usd)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (event_id) do nothing
            """,
            (calendar["event_id"], *cost.values()),
        )
    guardrail = event["guardrail"]
    conn.execute(
        """
        insert into policy_guardrail_source
          (event_id, monthly_budget_limit_usd, approval_required_over_usd,
           forbidden_actions, allowed_actions, policy_version)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (event_id) do nothing
        """,
        (
            calendar["event_id"],
            guardrail["monthly_budget_limit_usd"],
            guardrail["approval_required_over_usd"],
            json.dumps(guardrail["forbidden_actions"]),
            json.dumps(guardrail["allowed_actions"]),
            guardrail["policy_version"],
        ),
    )
def seed(conn) -> None:
    conn.execute(
        """
        insert into business_calendar
          (event_id, title, grade, target_users, max_delay_minutes, scheduled_at)
        values
          ('fomc-briefing', 'FOMC 주식 브리핑 푸시', 'S', 350000, 10, '08:30')
        on conflict (event_id) do update set
          title = excluded.title,
          grade = excluded.grade,
          target_users = excluded.target_users,
          max_delay_minutes = excluded.max_delay_minutes,
          scheduled_at = excluded.scheduled_at
        """
    )
    conn.execute(
        """
        insert into business_policy
          (event_id, vip_immediate, approval_required, max_general_delay_minutes)
        values
          ('fomc-briefing', true, true, 10)
        on conflict (event_id) do nothing
        """
    )
    conn.execute(
        """
        insert into event_mock_signal
          (
            event_id,
            baseline_peak_rps,
            shaped_peak_rps,
            required_app_pods,
            db_cpu_percent,
            cache_hit_ratio_percent,
            alb_status,
            eks_cost_usd,
            network_cost_usd,
            log_cost_usd,
            push_cost_usd,
            expected_value_usd,
            scale_down_rps_threshold
          )
        values
          ('fomc-briefing', 1420, 820, 29, 68, 91, 'ok', 31.2, 8.1, 3.4, 7.6, 4200, 600)
        on conflict (event_id) do update set
          baseline_peak_rps = excluded.baseline_peak_rps,
          shaped_peak_rps = excluded.shaped_peak_rps,
          required_app_pods = excluded.required_app_pods,
          db_cpu_percent = excluded.db_cpu_percent,
          cache_hit_ratio_percent = excluded.cache_hit_ratio_percent,
          alb_status = excluded.alb_status,
          eks_cost_usd = excluded.eks_cost_usd,
          network_cost_usd = excluded.network_cost_usd,
          log_cost_usd = excluded.log_cost_usd,
          push_cost_usd = excluded.push_cost_usd,
          expected_value_usd = excluded.expected_value_usd,
          scale_down_rps_threshold = excluded.scale_down_rps_threshold
        """
    )
    conn.execute(
        """
        insert into business_source_detail
          (
            event_id,
            push_channel,
            vip_audience_count,
            general_audience_count,
            campaign_importance,
            crm_segment,
            calendar_source
          )
        values
          (
            'fomc-briefing',
            'mobile-push',
            42000,
            308000,
            'tier-0-market-moving',
            'domestic-equity-active-traders',
            'temporary-business-calendar-fixture'
          )
        on conflict (event_id) do update set
          push_channel = excluded.push_channel,
          vip_audience_count = excluded.vip_audience_count,
          general_audience_count = excluded.general_audience_count,
          campaign_importance = excluded.campaign_importance,
          crm_segment = excluded.crm_segment,
          calendar_source = excluded.calendar_source
        """
    )
    conn.execute(
        """
        insert into traffic_observability_signal
          (
            event_id,
            alb_request_count_5m,
            prometheus_rps,
            p95_latency_ms,
            queue_depth,
            pod_cpu_percent,
            pod_memory_percent,
            hpa_current_replicas,
            hpa_desired_replicas
          )
        values
          ('fomc-briefing', 426000, 1420, 188, 7400, 63, 71, 18, 29)
        on conflict (event_id) do update set
          alb_request_count_5m = excluded.alb_request_count_5m,
          prometheus_rps = excluded.prometheus_rps,
          p95_latency_ms = excluded.p95_latency_ms,
          queue_depth = excluded.queue_depth,
          pod_cpu_percent = excluded.pod_cpu_percent,
          pod_memory_percent = excluded.pod_memory_percent,
          hpa_current_replicas = excluded.hpa_current_replicas,
          hpa_desired_replicas = excluded.hpa_desired_replicas
        """
    )
    conn.execute(
        """
        insert into infra_capacity_signal
          (
            event_id,
            eks_deployment_replicas,
            nodegroup_desired,
            nodegroup_max,
            rds_cpu_percent,
            rds_connections,
            rds_read_iops,
            redis_cache_hit_ratio_percent,
            alb_healthy_targets,
            alb_unhealthy_targets,
            nat_gateway_bytes_out_gb
          )
        values
          ('fomc-briefing', 18, 12, 30, 68, 640, 12500, 91, 18, 0, 37.4)
        on conflict (event_id) do update set
          eks_deployment_replicas = excluded.eks_deployment_replicas,
          nodegroup_desired = excluded.nodegroup_desired,
          nodegroup_max = excluded.nodegroup_max,
          rds_cpu_percent = excluded.rds_cpu_percent,
          rds_connections = excluded.rds_connections,
          rds_read_iops = excluded.rds_read_iops,
          redis_cache_hit_ratio_percent = excluded.redis_cache_hit_ratio_percent,
          alb_healthy_targets = excluded.alb_healthy_targets,
          alb_unhealthy_targets = excluded.alb_unhealthy_targets,
          nat_gateway_bytes_out_gb = excluded.nat_gateway_bytes_out_gb
        """
    )
    conn.execute(
        """
        insert into cost_signal
          (
            event_id,
            cost_explorer_month_to_date_usd,
            cur_projected_monthly_usd,
            kubecost_namespace_daily_usd,
            cloudwatch_logs_daily_usd,
            nat_alb_transfer_daily_usd,
            event_incremental_budget_usd
          )
        values
          ('fomc-briefing', 18420.55, 28600.00, 73.25, 11.80, 15.70, 95.00)
        on conflict (event_id) do update set
          cost_explorer_month_to_date_usd = excluded.cost_explorer_month_to_date_usd,
          cur_projected_monthly_usd = excluded.cur_projected_monthly_usd,
          kubecost_namespace_daily_usd = excluded.kubecost_namespace_daily_usd,
          cloudwatch_logs_daily_usd = excluded.cloudwatch_logs_daily_usd,
          nat_alb_transfer_daily_usd = excluded.nat_alb_transfer_daily_usd,
          event_incremental_budget_usd = excluded.event_incremental_budget_usd
        """
    )
    conn.execute(
        """
        insert into policy_guardrail_source
          (
            event_id,
            monthly_budget_limit_usd,
            approval_required_over_usd,
            forbidden_actions,
            allowed_actions,
            policy_version
          )
        values
          (
            'fomc-briefing',
            30000.00,
            50.00,
            %s,
            %s,
            'finops-policy-2026.06-temporary'
          )
        on conflict (event_id) do update set
          monthly_budget_limit_usd = excluded.monthly_budget_limit_usd,
          approval_required_over_usd = excluded.approval_required_over_usd,
          forbidden_actions = excluded.forbidden_actions,
          allowed_actions = excluded.allowed_actions,
          policy_version = excluded.policy_version
        """,
        (
            json.dumps(["disable_hpa", "scale_rds_down_during_event", "delete_warm_pool"]),
            json.dumps(["scale_out", "prewarm", "spread_push", "add_read_replica"]),
        ),
    )
    conn.execute(
        """
        insert into event_history
          (event_type, event_date, event_name,
           target_users, grade,
           actual_peak_rps, actual_shaped_rps,
           actual_pods_used, actual_cost_usd,
           actual_p95_ms, actual_duration_minutes,
           demand_shaping_window_minutes, peak_reduction_percent)
        values
          ('fomc','2025-11-07','FOMC November rate decision',
           340000,'S',1380,800,26,47.20,181,45,10,42),
          ('fomc','2025-09-18','FOMC September rate decision',
           360000,'S',1450,850,31,53.10,195,50,10,40),
          ('fomc','2025-07-30','FOMC July rate decision',
           320000,'S',1290,750,23,42.80,172,40,10,45),
          ('fomc','2025-05-07','FOMC May rate decision',
           330000,'S',1350,780,25,45.50,178,42,10,43),
          ('fomc','2025-03-19','FOMC March rate decision',
           310000,'S',1260,730,22,41.20,168,38,15,48)
        on conflict (event_type, event_date, event_name) do nothing
        """
    )
    for definition in TEST_EVENT_SEEDS:
        seed_event(conn, definition)


@activity.defn(name="load_event_context")
async def load_event_context(event_id: str) -> dict[str, Any]:
    return fetch_event_context(event_id)


@activity.defn(name="record_data_request")
async def record_data_request(workflow_id: str, phase: int, request: dict[str, Any]) -> None:
    if "target_agent" in request:
        receiver = request["target_agent"]
        required_fields = ", ".join(request.get("required_fields", [])) or "none"
        message = (
            f"Temporal Data Broker가 {receiver}에 '{request['operation']}' 작업을 요청했습니다. "
            f"필요 필드: {required_fields}. 요청 이유: {request.get('reason', '')}"
        )
        payload = {"type": "broker_data_request", **request}
    else:
        status = request.get("status", "requested")
        receiver = request["source_name"]
        message = (
            f"{request['requester_name']}가 {receiver}에게 "
            f"'{request['label']}' 값을 요청했습니다. "
            f"Temporal data_request 상태는 {status}입니다."
        )
        payload = {"type": "data_request", **request}
    with connect() as conn:
        conn.execute(
            """
            insert into agent_conversation_log
              (workflow_id, phase, sender, receiver, message, payload, created_at)
            values (%s, %s, 'Temporal Data Broker', %s, %s, %s, %s)
            """,
            (
                workflow_id,
                phase,
                receiver,
                message,
                json.dumps(payload),
                utcnow(),
            ),
        )


@activity.defn(name="record_agent_step_started")
async def record_agent_step_started(
    workflow_id: str,
    phase: int,
    agent_key: str,
    agent_name: str,
    next_agent_name: str,
    context: dict[str, Any],
) -> None:
    started_at = utcnow()
    with connect() as conn:
        conn.execute(
            """
            insert into agent_decision_log
              (workflow_id, phase, agent, status, result, created_at,
               agent_key, input_context, started_at)
            values (%s, %s, %s, 'running', %s, %s, %s, %s, %s)
            """,
            (
                workflow_id,
                phase,
                agent_name,
                json.dumps({"agent_key": agent_key, "next": next_agent_name}),
                started_at,
                agent_key,
                json.dumps(context),
                started_at,
            ),
        )
        conn.execute(
            """
            insert into agent_conversation_log
              (workflow_id, phase, sender, receiver, message, payload, created_at)
            values (%s, %s, 'FinOps Orchestrator', %s, %s, %s, %s)
            """,
            (
                workflow_id,
                phase,
                agent_name,
                f"{agent_name}에게 현재 이벤트 컨텍스트와 사용 가능한 이전 agent 결과를 전달했습니다.",
                json.dumps(
                    {
                        "agent_key": agent_key,
                        "status": "calling",
                        "available_results": list(context.get("agent_results", {}).keys()),
                    }
                ),
                started_at,
            ),
        )
        for exchange in build_agent_value_exchange(agent_key, agent_name, context):
            conn.execute(
                """
                insert into agent_conversation_log
                  (workflow_id, phase, sender, receiver, message, payload, created_at)
                values (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    workflow_id,
                    phase,
                    exchange["sender"],
                    exchange["receiver"],
                    exchange["message"],
                    json.dumps(exchange["payload"]),
                    utcnow(),
                ),
            )

    if AGENT_STEP_DELAY_SECONDS > 0:
        await asyncio.sleep(AGENT_STEP_DELAY_SECONDS)


@activity.defn(name="record_agent_step_completed")
async def record_agent_step_completed(
    workflow_id: str,
    phase: int,
    agent_key: str,
    agent_name: str,
    next_agent_name: str,
    context: dict[str, Any],
    raw_output: dict[str, Any],
) -> dict[str, Any]:
    response = normalize_agent_output(agent_key, agent_name, raw_output)
    output = response.model_dump(mode="json")
    result = response.result
    context["agent_results"][agent_key] = output
    for request in output["data_requests"]:
        context.setdefault("agent_declared_requests", []).append(
            {
                "requester_agent": agent_key,
                "requester_name": agent_name,
                **request,
            }
        )

    created_at = utcnow()
    with connect() as conn:
        conn.execute(
            """
            insert into agent_decision_log
              (workflow_id, phase, agent, status, result, created_at,
               agent_key, confidence, reasoning_source, evidence, warnings,
               data_requests, completed_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                workflow_id,
                phase,
                agent_name,
                response.status.value,
                json.dumps(
                    {
                        "result": result,
                        "evidence": output["evidence"],
                        "data_requests": output["data_requests"],
                        "confidence": output["confidence"],
                        "warnings": output["warnings"],
                        "reasoning_source": output["reasoning_source"],
                    }
                ),
                created_at,
                agent_key,
                response.confidence,
                response.reasoning_source,
                json.dumps(output["evidence"]),
                json.dumps(output["warnings"]),
                json.dumps(output["data_requests"]),
                created_at,
            ),
        )
        conn.execute(
            """
            insert into agent_conversation_log
              (workflow_id, phase, sender, receiver, message, payload, created_at)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                workflow_id,
                phase,
                agent_name,
                next_agent_name,
                output["message"],
                json.dumps(
                    {
                        "agent_key": agent_key,
                        "status": output["status"],
                        "result": result,
                        "evidence": output["evidence"],
                        "data_requests": output["data_requests"],
                        "confidence": output["confidence"],
                        "warnings": output["warnings"],
                        "reasoning_source": output["reasoning_source"],
                    }
                ),
                created_at,
            ),
        )
    return context
    
async def send_finops_report_to_slack(workflow_id: str, status: str, plan: dict[str, Any]) -> None:
    if not FINOPS_SLACK_OUTBOUND_QUEUE_URL or not FINOPS_SLACK_CHANNEL_ID:
        return

    report = plan.get("report", {})
    event = report.get("event", {})
    traffic = report.get("traffic", {})
    capacity = report.get("capacity", {})
    cost = report.get("cost", {})
    operations = report.get("operations", {})
    quality = plan.get("quality_gate_result", {})
    history = report.get("event_history", {})

    estimated_cost = cost.get("estimated_event_cost_usd", plan.get("estimated_cost_usd"))
    budget = cost.get("event_budget_usd")
    budget_usage = "-"
    if estimated_cost is not None and budget:
        try:
            budget_usage = f"{(float(estimated_cost) / float(budget)) * 100:.1f}%"
        except (TypeError, ValueError, ZeroDivisionError):
            budget_usage = "-"
    
    def money(value: Any) -> str:
        if value is None:
            return "-"
        try:
            return f"${float(value):.2f}"
        except (TypeError, ValueError):
            return str(value)

    ready_pods = capacity.get("ready_app_pods", "-")
    required_pods = traffic.get("required_app_pods", plan.get("required_app_pods", "-"))
    quality_label = "통과" if quality.get("passed") else "검토 필요"
    issues = quality.get("issues") or []
    warnings = quality.get("warnings") or []

    risk_lines = []
    if issues:
        risk_lines.extend([f"- {item}" for item in issues[:3]])
    if warnings:
        risk_lines.extend([f"- {item}" for item in warnings[:3]])
    if not risk_lines:
        risk_lines.append("- 주요 차단 이슈 없음")

    next_action = (
        "FinOps UI에서 Dry-run 승인 또는 재계획 여부를 결정하세요."
        if status != "plan_ready"
        else "FinOps UI에서 Dry-run 승인을 진행하세요."
    )

    payload = {
        "channel": FINOPS_SLACK_CHANNEL_ID,
        "text": f"FinOps 계획 보고서: {workflow_id}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "FinOps 계획 보고서"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*workflow_id:* `{workflow_id}`\n"
                        f"*상태:* `{status}` · *품질 검증:* `{quality_label}`"
                    ),
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*이벤트*\n{event.get('title', '-')}"},
                    {"type": "mrkdwn", "text": f"*등급 / 대상자*\n{event.get('grade', '-')} / {event.get('target_users', '-')}명"},
                    {"type": "mrkdwn", "text": f"*조정 후 Peak RPS*\n{traffic.get('peak_rps_after', plan.get('peak_rps_after', '-'))}"},
                    {"type": "mrkdwn", "text": f"*필요 Pod*\n{required_pods}개"},
                    {"type": "mrkdwn", "text": f"*Ready Pod*\n{ready_pods}/{required_pods}"},
                    {"type": "mrkdwn", "text": f"*예상 비용 / 예산*\n{money(estimated_cost)} / {money(budget)} ({budget_usage})"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*주요 리스크*\n" + "\n".join(risk_lines),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Fallback*\n"
                        f"VIP only: `{operations.get('fallback', {}).get('vip_only', '-')}` · "
                        f"General hold: `{operations.get('fallback', {}).get('general_hold', '-')}`"
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"역사 평균 Peak RPS: `{history.get('historical_avg_peak_rps', '-')}` · "
                            f"현재 예측: `{history.get('this_forecast_peak_rps', '-')}`"
                        ),
                    }
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*다음 액션*\n{next_action}"},
            },
        ],
    }

    sqs = boto3.client("sqs", region_name=AWS_REGION)
    response = await asyncio.to_thread(
        sqs.send_message,
        QueueUrl=FINOPS_SLACK_OUTBOUND_QUEUE_URL,
        MessageBody=json.dumps(payload),
    )
    print(f"[finops-slack] report queued: workflow_id={workflow_id}, message_id={response.get('MessageId')}")

@activity.defn(name="finalize_finops_plan")
async def finalize_finops_plan(workflow_id: str, context: dict[str, Any]) -> dict[str, Any]:
    plan = build_final_plan(context)
    plan["data_requests"] = context.get("data_requests", [])
    plan["agent_declared_requests"] = context.get("agent_declared_requests", [])
    plan["broker_call_log"] = context.get("broker_call_log", [])
    status = plan_status(plan)
    approval_status = "waiting" if status == "plan_ready" else "review_required"
    conversation_message = (
        "FinOps 계획과 후보 비교를 완성했습니다. 운영자 승인을 기다립니다."
        if status == "plan_ready"
        else "FinOps 보고서 품질 검증에 실패했습니다. issues를 검토하고 재계획해야 합니다."
    )
    created_at = utcnow()
    with connect() as conn:
        conn.execute(
            """
            insert into final_event_plan
              (workflow_id, event_id, status, plan, created_at, updated_at)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (workflow_id) do update set
              event_id = excluded.event_id,
              status = excluded.status,
              plan = excluded.plan,
              updated_at = excluded.updated_at
            """,
            (
                workflow_id,
                plan["event_id"],
                status,
                json.dumps(plan),
                created_at,
                created_at,
            ),
        )
        conn.execute(
            """
            insert into approval_request
              (workflow_id, status, requested_at)
            values (%s, %s, %s)
            on conflict (workflow_id) do update set
              status = excluded.status,
              requested_at = excluded.requested_at,
              decided_at = null,
              decided_by = null
            """,
            (workflow_id, approval_status, created_at),
        )
        conn.execute(
            """
            insert into agent_conversation_log
              (workflow_id, phase, sender, receiver, message, payload, created_at)
            values (%s, 99, 'FinOps Orchestrator', 'Operator', %s, %s, %s)
            """,
            (
                workflow_id,
                conversation_message,
                json.dumps({"plan": plan, "status": status}),
                utcnow(),
            ),
        )
    try:
        if FINOPS_SLACK_REPORT_ENABLED:
            await send_finops_report_to_slack(workflow_id, status, plan)
    except Exception as exc:
        print(f"[finops-slack] report send failed: {exc}")

    return {"workflow_id": workflow_id, "status": status, "plan": plan}
    


@activity.defn(name="load_execution_plan")
async def load_execution_plan(
    planning_workflow_id: str,
    execution_workflow_id: str,
    event_id: str,
    mode: str,
) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            select event_id, status, plan
            from final_event_plan
            where workflow_id = %s
            """,
            (planning_workflow_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"planning workflow not found: {planning_workflow_id}")
    final_plan = row[2] if isinstance(row[2], dict) else {}
    final_plan = {**final_plan, "status": row[1], "event_id": row[0]}
    precondition_result = validate_execution_preconditions(final_plan)
    steps = [
        step.model_dump(mode="json")
        for step in build_execution_steps(final_plan, ExecutionMode(mode))
    ] if precondition_result["valid"] else []
    return {
        "final_plan": final_plan,
        "steps": steps,
        "precondition_result": precondition_result,
        "event_id": row[0],
    }


@activity.defn(name="save_execution_plan")
async def save_execution_plan(
    execution_workflow_id: str,
    planning_workflow_id: str,
    event_id: str,
    mode: str,
    steps: list[dict[str, Any]],
    status: str,
) -> None:
    now = utcnow()
    plan = ExecutionPlan(
        planning_workflow_id=planning_workflow_id,
        execution_workflow_id=execution_workflow_id,
        event_id=event_id,
        mode=ExecutionMode(mode),
        steps=[ExecutionStep.model_validate(step) for step in steps],
        overall_status=status,
        created_at=now,
        completed_at=now if status in {"completed", "failed"} else None,
    )
    with connect() as conn:
        conn.execute(
            """
            insert into event_execution
              (execution_workflow_id, planning_workflow_id, event_id, mode, status,
               execution_plan, created_at, updated_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (execution_workflow_id) do update set
              status = excluded.status,
              execution_plan = excluded.execution_plan,
              updated_at = excluded.updated_at
            """,
            (
                execution_workflow_id,
                planning_workflow_id,
                event_id,
                mode,
                status,
                json.dumps(plan.model_dump(mode="json")),
                now,
                now,
            ),
        )


@activity.defn(name="execute_step")
async def execute_step(
    execution_workflow_id: str,
    step: dict[str, Any],
) -> dict[str, Any]:
    executed = simulate_step(ExecutionStep.model_validate(step))
    payload = executed.model_dump(mode="json")
    with connect() as conn:
        conn.execute(
            """
            insert into execution_step_log
              (execution_workflow_id, step_id, step_type, status, result,
               started_at, completed_at, created_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                execution_workflow_id,
                payload["step_id"],
                payload["step_type"],
                payload["status"],
                json.dumps(payload["result"]),
                payload["started_at"],
                payload["completed_at"],
                utcnow(),
            ),
        )
    return payload


@activity.defn(name="finalize_execution")
async def finalize_execution(
    execution_workflow_id: str,
    overall_status: str,
    completed_at: str,
) -> dict[str, Any]:
    with connect() as conn:
        conn.execute(
            """
            update event_execution
            set status = %s, updated_at = %s
            where execution_workflow_id = %s
            """,
            (overall_status, completed_at, execution_workflow_id),
        )
        step_rows = conn.execute(
            """
            select step_id, step_type, status, result, started_at, completed_at
            from execution_step_log
            where execution_workflow_id = %s
            order by id asc
            """,
            (execution_workflow_id,),
        ).fetchall()
    return {
        "execution_workflow_id": execution_workflow_id,
        "status": overall_status,
        "completed_at": completed_at,
        "step_count": len(step_rows),
    }


async def start_temporal_worker() -> None:
    global temporal_client
    temporal_client = await Client.connect(TEMPORAL_ADDRESS)
    worker = Worker(
        temporal_client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[FinOpsEventWorkflow, EventExecutionWorkflow],
        activities=[
            load_event_context,
            record_data_request,
            record_agent_step_started,
            record_agent_step_completed,
            finalize_finops_plan,
            load_execution_plan,
            save_execution_plan,
            execute_step,
            finalize_execution,
        ],
    )
    await worker.run()


@app.on_event("startup")
async def startup() -> None:
    global temporal_worker_task
    init_db()
    temporal_worker_task = asyncio.create_task(start_temporal_worker())


@app.on_event("shutdown")
async def shutdown() -> None:
    if temporal_worker_task:
        temporal_worker_task.cancel()


async def get_temporal_client() -> Client:
    global temporal_client
    if temporal_client is None:
        temporal_client = await Client.connect(TEMPORAL_ADDRESS)
    return temporal_client


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def list_events() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            select event_id, title, grade, target_users, scheduled_at
            from business_calendar
            order by event_id
            """
        ).fetchall()
    return [event_row_to_dict(row) for row in rows]


@app.get("/api/events")
def events() -> list[dict[str, Any]]:
    return list_events()


@app.get("/api/calendar")
def calendar() -> list[dict[str, Any]]:
    return list_events()


@app.get("/api/data-sources/{event_id}")
def data_sources(event_id: str) -> dict[str, Any]:
    context = fetch_event_context(event_id)
    return {
        "event_id": event_id,
        "business": context.get("business", {}),
        "traffic": context.get("traffic", {}),
        "infra": context.get("infra", {}),
        "cost": context.get("cost_source", {}),
        "policy": context.get("policy_source", {}),
        "live": context.get("live", {}),
    }


async def start_workflow_for_event(event_id: str) -> dict[str, str]:
    workflow_id = f"finops-{uuid.uuid4().hex[:8]}"
    try:
        client = await get_temporal_client()
        created_at = utcnow()
        with connect() as conn:
            conn.execute(
                """
                insert into final_event_plan
                  (workflow_id, event_id, status, plan, created_at, updated_at)
                values (%s, %s, 'running', %s, %s, %s)
                """,
                (
                    workflow_id,
                    event_id,
                    json.dumps({"event_id": event_id, "engine": "temporal", "phase": "starting"}),
                    created_at,
                    created_at,
                ),
            )
            conn.execute(
                """
                insert into agent_conversation_log
                  (workflow_id, phase, sender, receiver, message, payload, created_at)
                values (%s, 0, 'Operator', 'FinOps Orchestrator', %s, %s, %s)
                """,
                (
                    workflow_id,
                    "비즈니스 캘린더의 이벤트를 기준으로 FinOps 계획 수립을 요청했습니다.",
                    json.dumps({"event_id": event_id, "status": "requested"}),
                    created_at,
                ),
            )
            conn.execute(
                """
                insert into agent_conversation_log
                  (workflow_id, phase, sender, receiver, message, payload, created_at)
                values (%s, 0, 'FinOps Orchestrator', 'Temporal', %s, %s, %s)
                """,
                (
                    workflow_id,
                    f"Temporal task queue '{TEMPORAL_TASK_QUEUE}'에 FinOpsEventWorkflow 실행을 예약했습니다.",
                    json.dumps(
                        {
                            "event_id": event_id,
                            "workflow_id": workflow_id,
                            "task_queue": TEMPORAL_TASK_QUEUE,
                        }
                    ),
                    created_at,
                ),
            )
        await client.start_workflow(
            FinOpsEventWorkflow.run,
            args=[event_id, workflow_id],
            id=workflow_id,
            task_queue=TEMPORAL_TASK_QUEUE,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"temporal workflow failed: {exc}") from exc
    return {"workflow_id": workflow_id, "status": "running", "engine": "temporal"}


def _agent_response_from_decision_row(row: tuple[Any, ...]) -> dict[str, Any]:
    agent_name, status, payload, agent_key, confidence, reasoning_source, evidence, warnings, data_requests = row
    result_payload = payload if isinstance(payload, dict) else {}
    result = result_payload.get("result") if isinstance(result_payload.get("result"), dict) else result_payload
    return {
        "status": status,
        "agent_key": agent_key,
        "agent_name": agent_name,
        "result": result or {},
        "message": f"Reused from previous workflow: {agent_name}",
        "evidence": evidence or result_payload.get("evidence", []),
        "data_requests": data_requests or result_payload.get("data_requests", []),
        "confidence": float(confidence if confidence is not None else result_payload.get("confidence", 0.7)),
        "warnings": warnings or result_payload.get("warnings", []),
        "reasoning_source": reasoning_source or result_payload.get("reasoning_source", "rule"),
    }


async def start_replan_workflow(
    previous_workflow_id: str,
    intent: ReplanIntent,
) -> dict[str, Any]:
    new_workflow_id = f"{previous_workflow_id}-r{uuid.uuid4().hex[:4]}"
    with connect() as conn:
        plan_row = conn.execute(
            "select event_id from final_event_plan where workflow_id = %s",
            (previous_workflow_id,),
        ).fetchone()
        if not plan_row:
            raise HTTPException(status_code=404, detail="workflow not found")
        event_id = plan_row[0]
        rows = conn.execute(
            """
            select agent, status, result, agent_key, confidence, reasoning_source,
                   evidence, warnings, data_requests
            from agent_decision_log
            where workflow_id = %s
              and agent_key = any(%s)
              and status <> 'running'
            order by phase, id
            """,
            (previous_workflow_id, agents_before(intent.replan_from)),
        ).fetchall()

    previous_results: dict[str, Any] = {}
    for row in rows:
        agent_key = row[3]
        if agent_key:
            previous_results[agent_key] = _agent_response_from_decision_row(row)

    initial_context = build_replan_context(previous_results, intent)
    created_at = utcnow()
    try:
        client = await get_temporal_client()
        with connect() as conn:
            conn.execute(
                """
                insert into final_event_plan
                  (workflow_id, event_id, status, plan, created_at, updated_at)
                values (%s, %s, 'running', %s, %s, %s)
                """,
                (
                    new_workflow_id,
                    event_id,
                    json.dumps(
                        {
                            "event_id": event_id,
                            "engine": "temporal",
                            "phase": "replan_starting",
                            "previous_workflow_id": previous_workflow_id,
                            "replan_intent": intent.model_dump(mode="json"),
                        }
                    ),
                    created_at,
                    created_at,
                ),
            )
            conn.execute(
                """
                insert into agent_conversation_log
                  (workflow_id, phase, sender, receiver, message, payload, created_at)
                values (%s, 0, 'Operator', 'FinOps Orchestrator', %s, %s, %s)
                """,
                (
                    new_workflow_id,
                    f"Replan requested from {intent.replan_from}: {intent.reason}",
                    json.dumps(
                        {
                            "previous_workflow_id": previous_workflow_id,
                            "replan_intent": intent.model_dump(mode="json"),
                            "reused_agents": list(previous_results.keys()),
                        }
                    ),
                    created_at,
                ),
            )
        await client.start_workflow(
            FinOpsEventWorkflow.run,
            args=[event_id, new_workflow_id, initial_context],
            id=new_workflow_id,
            task_queue=TEMPORAL_TASK_QUEUE,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"temporal replan workflow failed: {exc}") from exc
    return {
        "new_workflow_id": new_workflow_id,
        "reused_agents": list(previous_results.keys()),
        "status": "running",
    }


@app.post("/api/workflows/run")
async def run_workflow(event_id: str = "fomc-briefing") -> dict[str, str]:
    return await start_workflow_for_event(event_id)


@app.get("/api/workflows")
def workflows() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            select workflow_id, event_id, status, plan, updated_at
            from final_event_plan
            order by updated_at desc
            limit 10
            """
        ).fetchall()
    return [
        {
            "workflow_id": row[0],
            "event_id": row[1],
            "status": row[2],
            "plan": row[3],
            "updated_at": row[4],
        }
        for row in rows
    ]


@app.get("/api/workflows/{workflow_id}/agents")
def workflow_agents(workflow_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            select agent, status, result, created_at, agent_key, confidence,
                   reasoning_source, evidence, warnings, data_requests,
                   input_context, started_at, completed_at
            from agent_decision_log
            where workflow_id = %s
            order by phase, id
            """,
            (workflow_id,),
        ).fetchall()
    structured_rows = [
        {
            "agent_name": row[0],
            "status": row[1],
            "result": row[2],
            "created_at": row[3],
            "agent_key": row[4],
            "confidence": row[5],
            "reasoning_source": row[6],
            "evidence": row[7],
            "warnings": row[8],
            "data_requests": row[9],
            "input_context": row[10],
            "started_at": row[11],
            "completed_at": row[12],
        }
        for row in rows
    ]
    return merge_agent_decision_rows(structured_rows, AGENT_SEQUENCE)


@app.get("/api/workflows/{workflow_id}/broker-log")
def workflow_broker_log(workflow_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        plan_row = conn.execute(
            "select plan from final_event_plan where workflow_id = %s",
            (workflow_id,),
        ).fetchone()
        if not plan_row:
            raise HTTPException(status_code=404, detail="workflow not found")
        payload_rows = conn.execute(
            """
            select payload
            from agent_conversation_log
            where workflow_id = %s
            order by phase, id
            """,
            (workflow_id,),
        ).fetchall()
    plan = plan_row[0] if isinstance(plan_row[0], dict) else {}
    payloads = [row[0] for row in payload_rows if isinstance(row[0], dict)]
    return normalize_broker_call_log(plan.get("broker_call_log", []), payloads)


@app.get("/api/agents/runtime")
def agent_runtime() -> dict[str, Any]:
    return {
        "namespace": FINOPS_NAMESPACE,
        "collected_at": utcnow(),
        "agents": collect_agent_runtime_status(),
    }


@app.post("/api/workflows/{workflow_id}/retry")
async def retry_workflow(workflow_id: str) -> dict[str, str]:
    with connect() as conn:
        row = conn.execute(
            "select event_id from final_event_plan where workflow_id = %s",
            (workflow_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")
    started = await start_workflow_for_event(row[0])
    return retry_response(started["workflow_id"])


@app.post("/api/workflows/{workflow_id}/replan")
async def replan_workflow(workflow_id: str, intent: ReplanIntent) -> dict[str, Any]:
    if intent.intent not in {"replan", "partial_replan"}:
        raise HTTPException(status_code=400, detail="intent must be replan or partial_replan")
    return await start_replan_workflow(workflow_id, intent)


@app.get("/api/workflows/{workflow_id}")
def workflow_detail(workflow_id: str) -> dict[str, Any]:
    with connect() as conn:
        plan = conn.execute(
            "select workflow_id, event_id, status, plan, updated_at from final_event_plan where workflow_id = %s",
            (workflow_id,),
        ).fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="workflow not found")
        logs = conn.execute(
            """
            select phase, agent, status, result, created_at
            from agent_decision_log
            where workflow_id = %s
            order by phase, id
            """,
            (workflow_id,),
        ).fetchall()
        conversation = conn.execute(
            """
            select phase, sender, receiver, message, payload, created_at
            from agent_conversation_log
            where workflow_id = %s
            order by phase, id
            """,
            (workflow_id,),
        ).fetchall()
    plan_body = plan[3] if isinstance(plan[3], dict) else {}
    return {
        "workflow_id": plan[0],
        "event_id": plan[1],
        "status": plan[2],
        "plan": plan[3],
        "data_requests": plan_body.get("data_requests", []),
        "agent_declared_requests": plan_body.get("agent_declared_requests", []),
        "plan_candidates": plan_body.get("plan_candidates", []),
        "recommended_candidate": plan_body.get("recommended_candidate"),
        "quality_gate_result": plan_body.get("quality_gate_result", {}),
        "updated_at": plan[4],
        "timeline": [
            {
                "phase": row[0],
                "agent": row[1],
                "status": row[2],
                "result": row[3],
                "created_at": row[4],
            }
            for row in logs
        ],
        "conversation": [conversation_row_to_dialogue(row) for row in conversation],
    }


@app.get("/api/workflows/{workflow_id}/conversation/brief")
async def workflow_conversation_brief(workflow_id: str) -> dict[str, Any]:
    with connect() as conn:
        plan = conn.execute(
            "select workflow_id, event_id, status, plan, updated_at from final_event_plan where workflow_id = %s",
            (workflow_id,),
        ).fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="workflow not found")
        logs = conn.execute(
            """
            select phase, agent, status, result, created_at
            from agent_decision_log
            where workflow_id = %s
            order by phase, id
            """,
            (workflow_id,),
        ).fetchall()
        conversation_rows = conn.execute(
            """
            select phase, sender, receiver, message, payload, created_at
            from agent_conversation_log
            where workflow_id = %s
            order by phase, id
            """,
            (workflow_id,),
        ).fetchall()

    timeline = [
        {
            "phase": row[0],
            "agent": row[1],
            "status": row[2],
            "result": row[3],
            "created_at": row[4],
        }
        for row in logs
    ]
    conversation = [conversation_row_to_dialogue(row) for row in conversation_rows]
    return await run_conversation_briefing_llm(
        workflow_id=plan[0],
        status=plan[2],
        conversation=conversation,
        timeline=timeline,
    )


@app.get("/api/executions/{execution_workflow_id}")
def execution_detail(execution_workflow_id: str) -> dict[str, Any]:
    with connect() as conn:
        execution = conn.execute(
            """
            select execution_workflow_id, planning_workflow_id, event_id, mode,
                   status, execution_plan, created_at, updated_at
            from event_execution
            where execution_workflow_id = %s
            """,
            (execution_workflow_id,),
        ).fetchone()
        if not execution:
            raise HTTPException(status_code=404, detail="execution not found")
        steps = conn.execute(
            """
            select step_id, step_type, status, result, started_at, completed_at
            from execution_step_log
            where execution_workflow_id = %s
            order by id asc
            """,
            (execution_workflow_id,),
        ).fetchall()
    return {
        "execution_workflow_id": execution[0],
        "planning_workflow_id": execution[1],
        "event_id": execution[2],
        "mode": execution[3],
        "status": execution[4],
        "execution_plan": execution[5],
        "created_at": execution[6],
        "updated_at": execution[7],
        "steps": [
            {
                "step_id": row[0],
                "step_type": row[1],
                "status": row[2],
                "result": row[3],
                "started_at": row[4],
                "completed_at": row[5],
            }
            for row in steps
        ],
    }


@app.get("/api/workflows/{workflow_id}/execution")
def workflow_execution(workflow_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            select execution_workflow_id
            from event_execution
            where planning_workflow_id = %s
            order by created_at desc
            limit 1
            """,
            (workflow_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="execution not found")
    return execution_detail(row[0])


@app.post("/api/workflows/{workflow_id}/approve")
async def approve(workflow_id: str, request: ApprovalRequest) -> dict[str, Any]:
    status = "approved" if request.decision == "approved" else "rejected"
    execution_workflow_id = None
    event_id = None
    with connect() as conn:
        existing = conn.execute(
            "select workflow_id, event_id from final_event_plan where workflow_id = %s",
            (workflow_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="workflow not found")
        event_id = existing[1]
        conn.execute(
            """
            update approval_request
            set status = %s, decided_at = %s, decided_by = %s
            where workflow_id = %s
            """,
            (status, utcnow(), request.approved_by, workflow_id),
        )
        final_status = "dry_run_completed" if status == "approved" else "rejected"
        conn.execute(
            """
            update final_event_plan
            set status = %s, updated_at = %s
            where workflow_id = %s
            """,
            (final_status, utcnow(), workflow_id),
        )
        if status == "approved":
            conn.execute(
                """
                insert into agent_decision_log
                  (workflow_id, phase, agent, status, result, created_at)
                values (%s, 100, 'Dry-run Execution', 'completed', %s, %s)
                """,
                (
                    workflow_id,
                    json.dumps(
                        {
                            "scale_app_pods": "dry_run_success",
                            "cdn_prewarm": "dry_run_success",
                            "push_schedule": "dry_run_success",
                        }
                    ),
                    utcnow(),
                ),
            )
            conn.execute(
                """
                insert into agent_conversation_log
                  (workflow_id, phase, sender, receiver, message, payload, created_at)
                values (%s, 100, 'FinOps Orchestrator', 'Operator', %s, %s, %s)
                """,
                (
                    workflow_id,
                    "승인을 확인했습니다. scale-out, pre-warm, push schedule 등록을 dry-run으로 검증했습니다.",
                    json.dumps({"status": "dry_run_completed"}),
                    utcnow(),
                ),
            )
    if status == "approved":
        execution_workflow_id = f"exec-{workflow_id}"
        try:
            client = await get_temporal_client()
            await client.start_workflow(
                EventExecutionWorkflow.run,
                args=[workflow_id, execution_workflow_id, event_id, "dry_run"],
                id=execution_workflow_id,
                task_queue=TEMPORAL_TASK_QUEUE,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"event execution workflow failed: {exc}",
            ) from exc
    return {
        "workflow_id": workflow_id,
        "status": final_status,
        "execution_workflow_id": execution_workflow_id,
    }


@activity.defn(name="run_chat_llm")
async def run_chat_llm(
    workflow_id: str,
    message: str,
    conversation_history: list[dict],
) -> dict[str, Any]:
    with connect() as conn:
        return await run_report_chat(
            conn,
            workflow_id=workflow_id,
            message=message,
            conversation_history=conversation_history,
        )


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    workflow_id = (request.workflow_id or "").strip()
    if not workflow_id:
        return {
            "answer": "실행된 Workflow가 없습니다. 먼저 FinOps 분석을 실행해주세요.",
            "sources": [],
            "tools_used": [],
            "conversation_history": [],
        }
    with connect() as conn:
        row = conn.execute(
            "select plan from final_event_plan where workflow_id = %s",
            (workflow_id,),
        ).fetchone()
    if not row:
        return {
            "answer": "실행된 Workflow가 없습니다. 먼저 FinOps 분석을 실행해주세요.",
            "sources": [],
            "tools_used": [],
            "conversation_history": [],
        }
    current_plan = row[0] if isinstance(row[0], dict) else {}
    with connect() as conn:
        intent = await run_planner_llm(
            conn,
            workflow_id=workflow_id,
            message=request.message.strip(),
            current_plan=current_plan,
        )
    if intent.intent == "explain":
        with connect() as conn:
            return await run_explain_llm(
                conn,
                workflow_id=workflow_id,
                message=request.message.strip(),
                conversation_history=request.conversation_history,
            )
    if intent.intent in {"replan", "partial_replan"}:
        if intent.requires_confirmation:
            return build_pending_replan_response(
                intent,
                request.conversation_history,
                request.message.strip(),
            )
        started = await start_replan_workflow(workflow_id, intent)
        history = request.conversation_history + [
            {"role": "user", "content": request.message.strip()},
            {
                "role": "assistant",
                "content": f"{intent.reason} 새 Workflow {started['new_workflow_id']}로 재계획을 시작했습니다.",
            },
        ]
        return {
            "answer": history[-1]["content"],
            "pending_replan": None,
            "new_workflow_id": started["new_workflow_id"],
            "reused_agents": started["reused_agents"],
            "sources": [],
            "tools_used": ["run_planner_llm", "start_replan_workflow"],
            "conversation_history": history,
        }
    return await run_chat_llm(
        workflow_id=workflow_id,
        message=request.message.strip(),
        conversation_history=request.conversation_history,
    )
    """
    DEPRECATED: legacy dummy chat response kept only as inert reference.
    message = request.message.strip()
    delay = 20 if "20" in message else 10
    return {
        "event_id": request.event_id,
        "agent": "Business Control Agent",
        "change_request": {
            "max_delivery_delay_minutes": delay,
            "push_window_minutes": delay,
            "requires_replan_from": "Demand Shaping Agent",
        },
        "answer": (
            f"요청을 구조화했습니다. 일반 사용자 발송 구간을 {delay}분으로 넓히려면 "
            "Demand Shaping 단계부터 다시 실행하면 됩니다."
        ),
    }
    """
