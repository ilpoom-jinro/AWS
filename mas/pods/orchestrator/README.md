# mas-orchestrator Pod

The orchestrator receives operator or internal requests and coordinates the
observer and analyzer pods.

```text
POST /analyze
  -> mas-observer-agent /observe
  -> mas-analyzer-agent /analyze-signals
```

It does not need Bedrock or Kubernetes read permissions directly.
