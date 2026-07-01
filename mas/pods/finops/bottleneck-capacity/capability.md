# Bottleneck Capacity Agent

## Role
Validate downstream bottlenecks across DB, Redis, ALB, and application capacity.

## Supported broker requests
- `validate_capacity`
- `check_bottleneck`
- Validate DB, cache, ALB, and pod readiness signals

## Returnable fields
- `db_cpu`
- `rds_connections`
- `rds_read_iops`
- `cache_hit_ratio`
- `alb_status`
- `alb_healthy_targets`
- `alb_unhealthy_targets`
- `ready_pods`
- `running_pods`
- `status`
- `validated_rps`
- `required_app_pods`
- `bottleneck_risk` when LLM assessment is applied
- `recommended_action` when LLM assessment is applied
- `reforecast_applied` when broker reforecast data exists
- `adjusted_capacity_rps` when broker reforecast data exists
- `pod_scaling_timeline` when broker reforecast data exists

## Unsupported requests
- Traffic forecast ownership
- Cost calculation
- Policy approval
- Real infrastructure execution
