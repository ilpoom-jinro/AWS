from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from app.agent_support import get_agent_result


AGENT_KEY = "cost"
AGENT_NAME = "Cost Agent"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    signals = context.get("signals", {})
    source = context.get("cost_source", {})
    infra = get_agent_result(context, "infra_execution")
    forecast = get_agent_result(context, "traffic_forecast")

    eks = float(signals.get("eks_cost_usd", 31.2))
    network = float(signals.get("network_cost_usd", 8.1))
    logs = float(signals.get("log_cost_usd", 3.4))
    push = float(signals.get("push_cost_usd", 7.6))
    budget = float(source.get("event_incremental_budget_usd", eks + network + logs + push))
    reference_pods = max(
        1,
        int(
            signals.get("required_app_pods")
            or infra.get("cost_reference_pods")
            or infra.get("current_app_pods")
            or 29
        ),
    )
    target_pods = int(infra["target_app_pods"])
    idle_saving = _idle_saving(context, infra, source)
    estimated_cost = _estimate_total_cost(
        eks=eks,
        network=network,
        logs=logs,
        push=push,
        pods=target_pods,
        reference_pods=reference_pods,
    )
    net_cost = round(estimated_cost - idle_saving, 2)
    budget_exceeded = estimated_cost > budget
    candidate_costs = _build_candidate_costs(
        forecast=forecast,
        infra=infra,
        eks=eks,
        network=network,
        logs=logs,
        push=push,
        reference_pods=reference_pods,
        idle_saving=idle_saving,
        budget=budget,
    )
    source_name = (
        "aws_cur_athena+cost_signal"
        if source.get("cost_source_type") == "aws_cur_athena"
        else "cost_signal"
    )
    result = {
        "eks": eks,
        "network": network,
        "logs": logs,
        "push": push,
        "total": estimated_cost,
        "estimated_cost_usd": estimated_cost,
        "gross_estimated_cost_usd": estimated_cost,
        "idle_resource_saving_usd": idle_saving,
        "net_cost_after_idle_reduction": net_cost,
        "budget_exceeded": budget_exceeded,
        "net_budget_exceeded": net_cost > budget,
        "pod_count": target_pods,
        "reference_pods": reference_pods,
        "cost_explorer_month_to_date_usd": source.get(
            "cur_month_to_date_usd",
            source.get("cost_explorer_month_to_date_usd"),
        ),
        "cur_month_to_date_usd": source.get("cur_month_to_date_usd"),
        "cur_projected_monthly_usd": source.get("cur_projected_monthly_usd"),
        "kubecost_namespace_daily_usd": float(source.get("kubecost_namespace_daily_usd", 0)),
        "event_incremental_budget_usd": budget,
        "candidate_costs": candidate_costs,
        "cost_optimization_summary": {
            "idle_resource_saving_usd": idle_saving,
            "candidate_count": len(candidate_costs),
            "source_plan": "infra_execution.candidate_capacity_plans",
        },
        "source": source_name,
        "evidence": [
            f"Infra Capacity Plan target_app_pods={target_pods}를 사용했습니다.",
            f"비용 기준 Pod 수는 {reference_pods}개입니다.",
            f"EKS 기준 비용은 ${eks}입니다.",
            f"Network 비용은 ${network}입니다.",
            f"Log 비용은 ${logs}입니다.",
            f"Push 비용은 ${push}입니다.",
            f"유휴 자원 절감 가능액은 ${idle_saving}입니다.",
            f"총 비용은 ${estimated_cost}, 절감 반영 순비용은 ${net_cost}입니다.",
            f"이벤트 증분 예산은 ${budget}입니다.",
            f"budget_exceeded={budget_exceeded}입니다.",
            f"비용 데이터 source는 {source_name}입니다.",
        ],
    }
    if infra.get("idle_resource_plan"):
        result["idle_resource_plan"] = infra.get("idle_resource_plan", [])
    try:
        cluster_state = get_agent_result(context, "cluster_state")
    except KeyError:
        cluster_state = {}
    if cluster_state.get("idle_candidates"):
        result["idle_candidates"] = cluster_state.get("idle_candidates", [])
    now = datetime.now(timezone.utc)
    cur_data = query_cur_via_athena(year=str(now.year), month=str(now.month))
    if cur_data:
        result["cost_explorer_month_to_date_usd"] = cur_data["total_cost"]
        result["cur_eks_cost"] = cur_data["eks_cost"]
        result["cur_ec2_cost"] = cur_data["ec2_cost"]
        result["cur_rds_cost"] = cur_data["rds_cost"]
        result["cost_data_source"] = "athena_cur"
    else:
        result["cost_explorer_month_to_date_usd"] = result.get(
            "cost_explorer_month_to_date_usd",
            source.get("cost_explorer_month_to_date_usd", 18420.55),
        )
        result["cost_data_source"] = "seed_fallback"
        result.setdefault("warnings", []).append(
            "CUR Athena lookup failed; using seeded cost data."
        )

    return (
        result,
        (
            f"Estimated gross cost is ${estimated_cost}; "
            f"net cost after idle reduction is ${net_cost} "
            f"for {target_pods} target pods."
        ),
    )


def _build_candidate_costs(
    *,
    forecast: dict[str, Any],
    infra: dict[str, Any],
    eks: float,
    network: float,
    logs: float,
    push: float,
    reference_pods: int,
    idle_saving: float,
    budget: float,
) -> list[dict[str, Any]]:
    candidate_capacity_by_label = {
        item.get("label"): item for item in infra.get("candidate_capacity_plans", [])
    }
    current_pods = int(infra.get("current_app_pods") or 0)
    candidate_costs = []
    for candidate in forecast.get("candidate_forecasts", []):
        label = candidate["label"]
        capacity_plan = candidate_capacity_by_label.get(label, {})
        pods = int(candidate["required_app_pods"])
        gross_cost = _estimate_total_cost(
            eks=eks,
            network=network,
            logs=logs,
            push=push,
            pods=pods,
            reference_pods=reference_pods,
        )
        net_cost = round(gross_cost - idle_saving, 2)
        candidate_costs.append(
            {
                "label": label,
                "estimated_cost_usd": gross_cost,
                "gross_cost_usd": gross_cost,
                "idle_resource_saving_usd": idle_saving,
                "net_cost_after_idle_reduction": net_cost,
                "budget_exceeded": gross_cost > budget,
                "net_budget_exceeded": net_cost > budget,
                "required_app_pods": pods,
                "scale_out_pods": capacity_plan.get(
                    "scale_out_pods",
                    max(0, pods - current_pods),
                ),
                "additional_nodes_required": capacity_plan.get("additional_nodes_required"),
            }
        )
    return candidate_costs


def _idle_saving(context: dict[str, Any], infra: dict[str, Any], source: dict[str, Any]) -> float:
    idle_saving = float(
        infra.get("idle_resource_saving_usd")
        or source.get("idle_resource_saving_usd")
        or 0
    )
    if idle_saving > 0:
        return idle_saving
    try:
        cluster_state = get_agent_result(context, "cluster_state")
    except KeyError:
        cluster_state = {}
    return float(cluster_state.get("total_estimated_saving_usd", 0) or 0)


def _estimate_total_cost(
    *,
    eks: float,
    network: float,
    logs: float,
    push: float,
    pods: int,
    reference_pods: int,
) -> float:
    scaled_eks = eks * max(1, pods) / max(1, reference_pods)
    return round(scaled_eks + network + logs + push, 2)


def query_cur_via_athena(year: str, month: str) -> dict[str, float | str] | None:
    try:
        import boto3
    except Exception:
        return None

    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2"))
    database = os.getenv(
        "ATHENA_CUR_DATABASE",
        os.getenv("FINOPS_ATHENA_DATABASE", "financial_ops_cur"),
    )
    table = os.getenv(
        "ATHENA_CUR_TABLE",
        os.getenv("FINOPS_ATHENA_TABLE", "financial_ops_cur"),
    )
    output_location = os.getenv(
        "ATHENA_OUTPUT_LOCATION",
        os.getenv(
            "FINOPS_ATHENA_OUTPUT_LOCATION",
            "s3://financial-ops-cur-609540154179-ap-northeast-2/athena-results/",
        ),
    )
    timeout_seconds = int(os.getenv("ATHENA_TIMEOUT_SECONDS", "30"))
    query = f"""
    SELECT
      line_item_usage_account_id,
      SUM(line_item_blended_cost) AS total_cost,
      SUM(CASE
        WHEN line_item_product_code = 'AmazonEKS'
        THEN line_item_blended_cost ELSE 0
      END) AS eks_cost,
      SUM(CASE
        WHEN line_item_product_code = 'AmazonEC2'
        THEN line_item_blended_cost ELSE 0
      END) AS ec2_cost,
      SUM(CASE
        WHEN line_item_product_code = 'AmazonRDS'
        THEN line_item_blended_cost ELSE 0
      END) AS rds_cost
    FROM {database}.{table}
    WHERE year = '{year}'
      AND month = '{month}'
    GROUP BY line_item_usage_account_id
    LIMIT 1
    """

    try:
        athena = boto3.client("athena", region_name=region)
        response = athena.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": database},
            ResultConfiguration={"OutputLocation": output_location},
        )
        execution_id = response["QueryExecutionId"]
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(2)
            status = athena.get_query_execution(QueryExecutionId=execution_id)
            state = status["QueryExecution"]["Status"]["State"]
            if state == "SUCCEEDED":
                break
            if state in {"FAILED", "CANCELLED"}:
                return None
        else:
            return None

        results = athena.get_query_results(QueryExecutionId=execution_id)
        rows = results.get("ResultSet", {}).get("Rows", [])
        if len(rows) < 2:
            return None

        columns = [item["VarCharValue"] for item in rows[0]["Data"]]
        values = [item.get("VarCharValue", "0") for item in rows[1]["Data"]]
        row = dict(zip(columns, values))
        return {
            "total_cost": round(float(row.get("total_cost", 0)), 2),
            "eks_cost": round(float(row.get("eks_cost", 0)), 2),
            "ec2_cost": round(float(row.get("ec2_cost", 0)), 2),
            "rds_cost": round(float(row.get("rds_cost", 0)), 2),
            "source": "athena_cur",
        }
    except Exception:
        return None


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
