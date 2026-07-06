from __future__ import annotations

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
        "budget_exceeded": budget_exceeded,
        "pod_count": infra["target_app_pods"],
        "cost_explorer_month_to_date_usd": source.get("cur_month_to_date_usd", source.get("cost_explorer_month_to_date_usd")),
        "cur_month_to_date_usd": source.get("cur_month_to_date_usd"),
        "cur_projected_monthly_usd": source.get("cur_projected_monthly_usd"),
        "kubecost_namespace_daily_usd": float(source.get("kubecost_namespace_daily_usd", 0)),
        "event_incremental_budget_usd": budget,
        "candidate_costs": candidate_costs,
        "source": source_name,
        "evidence": [
            f"Infra Execution Agent의 target_app_pods={infra['target_app_pods']} 값을 사용했습니다.",
            f"EKS 추가 비용은 ${eks}입니다.",
            f"Network 비용은 ${network}입니다.",
            f"Log 비용은 ${logs}입니다.",
            f"Push 비용은 ${push}입니다.",
            f"총 비용 계산식은 {eks} + {network} + {logs} + {push} = ${estimated_cost}입니다.",
            f"이벤트 증분 예산은 ${budget}입니다.",
            f"budget_exceeded={budget_exceeded}입니다.",
            f"비용 데이터 source는 {source_name}입니다.",
        ],
        
    }
    return result, f"Estimated incremental cost is ${estimated_cost} for {infra['target_app_pods']} target pods."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
