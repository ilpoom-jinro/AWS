# Bottleneck Capacity Agent

## Role
Validate downstream bottlenecks across DB, Redis, ALB, and application capacity.

## Supported broker requests
- Validate database or cache capacity signals
- Assess bottleneck risk from forecast and infrastructure signals
- Request traffic forecast re-evaluation when needed

## Returnable fields
- `db_cpu_percent`
- `rds_connections`
- `rds_read_iops`
- `cache_hit_ratio_percent`
- `risk_level`
- `bottleneck`

## Unsupported requests
- Traffic forecast ownership
- Cost calculation
- Policy approval
- Real infrastructure execution
