# Demand Shaping Agent

## Role
Design push delivery windows and demand shaping candidates.

## Supported broker requests
- Return peak reduction
- Return push window candidates
- Recalculate shaping under changed delay constraints

## Returnable fields
- `send_window_minutes`
- `peak_reduction_percent`
- `candidates`
- `vip_send_mode`
- `general_send_mode`

## Unsupported requests
- Traffic forecast ownership
- Cost calculation
- Infrastructure execution
