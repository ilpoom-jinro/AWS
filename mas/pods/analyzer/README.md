# mas-analyzer-agent Pod

The analyzer receives structured signals from the orchestrator and asks Bedrock
for an operational analysis.

```text
POST /analyze-signals
  -> Bedrock Runtime
  -> returns analysis
```
