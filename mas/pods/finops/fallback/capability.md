# Fallback Agent

## Role
Prepare fallback actions when the primary FinOps plan is risky or blocked.

## Supported broker requests
- Build fallback plan from policy and capacity context
- Describe safe rollback or degrade-mode options

## Returnable fields
- `fallback_plan`
- `rollback_steps`
- `degrade_mode`

## Unsupported requests
- Real rollback execution
- Cost calculation
- Traffic forecasting
