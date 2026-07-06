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
    estimated_cost = round(eks + network + logs + push, 2)
    budget_exceeded = estimated_cost > budget
    base_pods = max(1, int(infra["target_app_pods"]))
    candidate_costs = []
    for candidate in forecast.get("candidate_forecasts", []):
        candidate_eks_cost = eks * candidate["required_app_pods"] / base_pods
        candidate_estimated_cost = round(
            candidate_eks_cost + network + logs + push,
            2,
        )
        candidate_costs.append(
            {
                "label": candidate["label"],
                "estimated_cost_usd": candidate_estimated_cost,
                "budget_exceeded": candidate_estimated_cost > budget,
            }
        )
    result = {
        "eks": eks,
        "network": network,
        "logs": logs,
        "push": push,
        "total": estimated_cost,
        "estimated_cost_usd": estimated_cost,
        "budget_exceeded": budget_exceeded,
        "pod_count": infra["target_app_pods"],
        "cost_explorer_month_to_date_usd": source.get("cur_month_to_date_usd", source.get("cost_explorer_month_to_date_usd")),
        "cur_month_to_date_usd": source.get("cur_month_to_date_usd"),
        "cur_projected_monthly_usd": source.get("cur_projected_monthly_usd"),
        "kubecost_namespace_daily_usd": float(source.get("kubecost_namespace_daily_usd", 0)),
        "event_incremental_budget_usd": budget,
        "candidate_costs": candidate_costs,
        "source": "aws_cur_athena+cost_signal"
        if source.get("cost_source_type") == "aws_cur_athena"
        else "cost_signal",
    }
    try:
        cluster_state = get_agent_result(context, "cluster_state")
    except KeyError:
        cluster_state = {}
    idle_saving = float(cluster_state.get("total_estimated_saving_usd", 0) or 0)
    if idle_saving > 0:
        result["idle_resource_saving_usd"] = idle_saving
        result["net_cost_after_idle_reduction"] = round(
            result.get("estimated_cost_usd", 0) - idle_saving,
            2,
        )
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
    return result, f"Estimated incremental cost is ${estimated_cost} for {infra['target_app_pods']} target pods."


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
