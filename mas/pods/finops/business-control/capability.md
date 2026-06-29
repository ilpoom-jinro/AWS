# Business Control Agent

## Role
Classify the business event and derive initial business constraints.

## Supported broker requests
- Return target users
- Return allowed delay
- Return VIP handling assumptions

## Returnable fields
- `target_users`
- `max_delay_minutes`
- `vip_user_count`
- `grade`

## Unsupported requests
- Traffic forecasting
- Infrastructure execution
- Cost calculation
