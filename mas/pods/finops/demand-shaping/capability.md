# Demand Shaping Agent

## Role
Design push delivery windows and demand shaping candidates.

## Supported broker requests
- Return the selected send window
- Return peak reduction
- Return candidate shaping plans
- Recalculate shaping under changed delay constraints

## Returnable fields
- `send_window_minutes`
- `peak_reduction_percent`
- `vip_send_mode`
- `general_send_mode`
- `candidates`
  - `label`
  - `push_window_minutes`
  - `peak_reduction_percent`

## Unsupported requests
- Traffic forecast ownership
- Bottleneck validation
- Cost calculation
- Infrastructure execution
