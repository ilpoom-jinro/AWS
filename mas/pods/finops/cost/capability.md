# Cost Agent

## Role
Estimate incremental event cost from the proposed capacity plan.

## Supported broker requests
- Estimate candidate cost
- Recalculate cost under changed pod or window assumptions

## Returnable fields
- `total`
- `estimated_cost_usd`
- `budget_exceeded`
- `candidate_costs`
- `budget`

## Unsupported requests
- Traffic forecasting
- Policy approval
- Real billing or AWS budget changes
