# Postmortem Learning Agent

## Role
Prepare learning items for forecast-vs-actual and cost-vs-actual review.

## Supported broker requests
- `prepare_learning`
- Return forecast and cost baselines for post-event comparison

## Returnable fields
- `profile_update`
- `compare`
- `forecast_peak_rps`
- `forecast_cost_usd`

## Unsupported requests
- Real postmortem execution
- Live metrics collection
- Infrastructure changes
