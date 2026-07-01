# Cost Agent

## Role
Estimate incremental event cost from the proposed capacity plan.

## Supported broker requests
- `estimate_candidate`
- `recalculate`
- Estimate candidate cost under changed pod or window assumptions

## Returnable fields
- `eks`
- `network`
- `logs`
- `push`
- `total`
- `estimated_cost_usd`
- `budget_exceeded`
- `pod_count`
- `cost_explorer_month_to_date_usd`
- `cur_month_to_date_usd`
- `cur_projected_monthly_usd`
- `kubecost_namespace_daily_usd`
- `event_incremental_budget_usd`
- `candidate_costs`
  - `label`
  - `estimated_cost_usd`
  - `budget_exceeded`

## Unsupported requests
- Traffic forecasting
- Policy approval
- Real billing or AWS budget changes
