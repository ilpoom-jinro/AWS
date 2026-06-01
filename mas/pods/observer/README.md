# mas-observer-agent Pod

The observer reads operational signals. It does not call Bedrock.

```text
POST /observe
  -> Prometheus query
  -> Kubernetes read-only API
  -> returns structured signals
```
