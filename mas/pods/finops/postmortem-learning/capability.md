# Postmortem Learning Agent

## Role
Prepare learning items for forecast-vs-actual and cost-vs-actual review.

## Supported broker requests
- Summarize forecast baseline
- Summarize cost baseline
- Prepare post-event learning checklist

## Returnable fields
- `forecast_baseline`
- `cost_baseline`
- `learning_items`

## Unsupported requests
- Real postmortem execution
- Live metrics collection
- Infrastructure changes
