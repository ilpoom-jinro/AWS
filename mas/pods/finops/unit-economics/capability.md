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
- `gross_cost_usd`
  - Total estimated cost before idle-resource savings
- `idle_saving_usd`
  - Estimated savings from idle-resource reduction candidates
- `net_cost_usd`
  - Net cost after idle-resource savings
- `cost_to_value_percent`
  - Net cost as a percentage of expected business value
- `value_per_dollar`
  - Expected business value per 1 USD of net cost
- `candidate_economics`
  - Candidate-level economics comparison
  - Includes `gross_cost_usd`, `net_cost_usd`, `cost_to_value_percent`, `value_per_dollar`, `budget_status`
- `selected_candidate_label`
  - Candidate label used as the primary economics recommendation
- `economic_assessment`
  - Overall economics assessment: `positive` or `needs_review`
- `economic_summary`
  - Human-readable economics summary

## Unsupported requests
- Infrastructure scaling
- Traffic forecasting
- Policy enforcement
