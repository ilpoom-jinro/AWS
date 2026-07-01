# Observer Agent

## Role
Design monitoring criteria for the event window and define scale-down conditions.

## Supported broker requests
- `generate_monitoring_plan`
- Build monitoring criteria from forecast data
- Calculate scale-down and alert thresholds

## Returnable fields
- `mode`
- `watch`
- `recommendation`
- `forecast_peak_rps`
- `forecast_required_pods` when broker reforecast data exists
- `forecast_p95_ms` when broker reforecast data exists
- `approval_required`
- `broker_reforecast_applied` when broker reforecast data exists
- `scale_down_rps_threshold`
- `alert_rps_threshold`
- `monitoring_interval_seconds`

## Unsupported requests
- Real monitoring execution
- Live metrics collection
- Direct AWS CloudWatch calls

## Broker failure policy
If a broker reforecast fails, return completed using the existing traffic forecast,
record a warning, and continue.
