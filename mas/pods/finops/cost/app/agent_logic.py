from __future__ import annotations

from typing import Any


AGENT_KEY = "cost"
AGENT_NAME = "Cost Agent"
LLM_PROMPT = None


def evaluate(context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    signals = context.get("signals", {})
    source = context.get("cost_source", {})
    infra = context["agent_results"]["infra_execution"]
    eks = float(signals.get("eks_cost_usd", 31.2))
    network = float(signals.get("network_cost_usd", 8.1))
    logs = float(signals.get("log_cost_usd", 3.4))
    push = float(signals.get("push_cost_usd", 7.6))
    budget = float(source.get("event_incremental_budget_usd", eks + network + logs + push))
    total = round(min(eks + network + logs + push, budget), 2)
    result = {
        "eks": eks,
        "network": network,
        "logs": logs,
        "push": push,
        "total": total,
        "pod_count": infra["target_app_pods"],
        "cost_explorer_month_to_date_usd": source.get("cost_explorer_month_to_date_usd"),
        "cur_projected_monthly_usd": source.get("cur_projected_monthly_usd"),
        "kubecost_namespace_daily_usd": float(source.get("kubecost_namespace_daily_usd", 0)),
        "event_incremental_budget_usd": budget,
        "source": "aws_cost_explorer+cost_signal"
        if source.get("cost_explorer_source") == "aws_cost_explorer"
        else "cost_signal",
    }
    return result, f"Estimated incremental cost is ${total} for {infra['target_app_pods']} target pods."


def apply_llm(result: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    return result
