# Infra Execution Agent

## Role
Convert required capacity into an infrastructure execution plan.

## Supported broker requests
- Validate capacity plan
- Return target pod count
- Describe dry-run execution steps

## Returnable fields
- `target_app_pods`
- `scale_out_at`
- `prewarm_at`
- `capacity_validated`
- `dry_run_steps`

## Unsupported requests
- Real AWS or Kubernetes execution in planning mode
- Cost and unit-economics calculations
- Business policy decisions
