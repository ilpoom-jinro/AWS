# Fallback Agent

## Role
Prepare fallback actions when the primary FinOps plan is risky or blocked.

## Supported broker requests
- `generate_fallback_plan`
- Describe safe fallback flags from policy context

## Returnable fields
- `vip_only`
- `general_hold`
- `static_report`
- `allowed_actions`
- `excluded_actions`

## Unsupported requests
- Real rollback execution
- Cost calculation
- Traffic forecasting
