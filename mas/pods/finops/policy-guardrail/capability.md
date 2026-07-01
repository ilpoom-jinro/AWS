# Policy Guardrail Agent

## Role
Validate the plan against policy guardrails and approval requirements.

## Supported broker requests
- `validate_policy`
- `validate_cost_value_alignment`
- Check allowed actions
- Determine approval requirements

## Returnable fields
- `allowed`
- `forbidden`
- `approval_required`
- `cost_ratio`
- `monthly_budget_limit_usd`
- `approval_required_over_usd`
- `policy_version`
- `proceed` when LLM assessment is applied
- `conditions` when LLM assessment is applied
- `policy_reasoning` when LLM assessment is applied

## Unsupported requests
- Cost calculation
- Traffic forecasting
- Real approval execution
