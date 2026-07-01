# Traffic Forecast Agent

## Role
Forecast event traffic after demand shaping and estimate required application pods.

## Supported broker requests
- `reforecast`
- `reforecast_with_updated_constraints`
- `reforecast_with_demand_shaping_update`
- `validate_forecast`

## Returnable fields
- `peak_rps_before`
- `peak_rps_after`
- `required_app_pods`
- `send_window_minutes`
- `peak_reduction_percent`
- `p95_latency_ms`
- `estimated_p95_ms`
  - Alias resolved from `candidate_forecasts[].estimated_p95_ms`
  - Or from top-level `p95_latency_ms`
- `candidate_forecasts`
  - `label`
  - `push_window_minutes`
  - `peak_rps_after`
  - `required_app_pods`
  - `estimated_p95_ms`
- `reforecast`
- `adjusted_capacity_rps` when pod readiness constraints are provided
- `pod_scaling_timeline` when pod readiness constraints are provided
- `risk_assessment` when pod readiness constraints are provided

## Unsupported requests
- Real AWS, Kubernetes, or execution changes
- Cost calculation
- Policy approval or compliance decisions
- Database or cache bottleneck ownership such as `db_cpu`, `rds_connections`, or `cache_hit_ratio`
