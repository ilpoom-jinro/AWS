# mas-runtime Pod

`mas-runtime` is the first MAS agent pod. It combines a small API surface,
observer behavior, and analyzer behavior so the platform can verify the full
path from Ops EKS to Prometheus, Kubernetes, and Bedrock.

## Runtime

```text
Deployment: mas-runtime
Namespace: mas
ServiceAccount: mas-runtime
Image: financial/mas-runtime
```

## Responsibilities

```text
/health           pod readiness and identity
/prometheus-test  Prometheus API connectivity
/kubernetes-test  Kubernetes read-only connectivity
/bedrock-test     Bedrock Runtime connectivity
/analyze          collect Prometheus signals and ask Bedrock for analysis
```

## Files

```text
mas/pods/runtime/Dockerfile   container image for this pod type
mas/pods/runtime/agent.yml    Kubernetes deployment config consumed by Ansible
vpc/ops/mas-runtime.tf        IAM and Pod Identity for this service account
```
