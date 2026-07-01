# Business Control Agent

## Role
Classify the business event and expose business constraints from the event calendar,
business profile, and policy.

## Supported broker requests
- Return event classification data
- Return audience counts
- Return approval and delay constraints

## Returnable fields
- `event_id`
- `grade`
- `target_users`
- `vip_audience_count`
- `general_audience_count`
- `push_channel`
- `campaign_importance`
- `approval_required`
- `max_delay_minutes`

## Unsupported requests
- Traffic forecasting
- Bottleneck validation
- Infrastructure execution
- Cost calculation
