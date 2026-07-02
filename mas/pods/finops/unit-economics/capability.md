# Unit Economics Agent

## Role
Compare expected event value against incremental cost.

## Supported broker requests
- `recalculate`
- `validate_cost_value_alignment`
- `validate_cost_efficiency_with_business_impact`

## Returnable fields
- `expected_value_usd`
- `cost_ratio`
- `override`
- `estimated_cost_usd`
- `cost_efficiency_score`
  - Cost efficiency score calculated as `expected_value_usd / estimated_cost_usd`
- `roi_validation`
  - ROI validation result: `positive` or `negative`
- `business_impact_assessment`
  - Business impact assessment:
    - `high_value_tier1_event`
    - `high_value_event`
    - `medium_value_event`
    - `standard_event`
- `final_approval_recommendation`
  - Final approval recommendation:
    - `auto_approvable`
    - `requires_human_approval_budget_exceeded`
    - `requires_human_approval_infra_risk`
    - `requires_human_approval_budget_and_infra_risk`

## Unsupported requests
- Infrastructure scaling
- Traffic forecasting
- Policy enforcement
