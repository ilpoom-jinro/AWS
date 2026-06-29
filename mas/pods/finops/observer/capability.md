# Observer Agent

## Role
Design monitoring criteria for the event window and define scale-down conditions.

## Supported broker requests
- Build monitoring thresholds from forecast data
- Calculate scale-down thresholds

## Returnable fields
- `scale_down_rps_threshold`
- `alert_rps_threshold`
- `monitoring_interval_seconds`

## Unsupported requests
- Real monitoring execution
- Live metrics collection
- Direct AWS CloudWatch calls

## Broker failure policy
If a broker reforecast fails, do not finish as blocked.
Use the existing `traffic_forecast` result to build monitoring criteria,
record a warning, and return completed.
