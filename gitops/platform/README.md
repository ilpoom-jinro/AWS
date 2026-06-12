# JINRO Cluster YAML Drafts

This folder separates Kubernetes manifests and Helm values by target EKS cluster.

These files are drafts for review and GitOps migration. Container images must be
stored in ECR, while these YAML files should live in Git and be applied by Argo CD.

## Clusters

| Cluster | VPC | Purpose |
|---|---|---|
| `financial-service-eks` | service/globalservice VPC | Frontend, backend, and service VPC Alloy |
| `financial-ops-eks` | ops/internal VPC | Grafana, Loki, Thanos, Alertmanager, and ops VPC Alloy |

## Values Injected Automatically Into Internal Gitea

GitHub keeps reusable placeholders. `gitops-platform-sync.yml` replaces the
infrastructure-specific values only in the internal Gitea deployment copy.

| Placeholder | Automatically Replaced With |
|---|---|
| `REPLACE_WITH_OPS_VPC_ID` | Current Ops EKS VPC ID |
| `REPLACE_WITH_OPS_LOKI_NLB_SG_ID` | Current Loki internal NLB security group ID |
| `REPLACE_WITH_OPS_THANOS_RECEIVE_NLB_SG_ID` | Current Thanos Receive internal NLB security group ID |
| `loki-internal-nlb.example.local` | Loki internal NLB DNS |
| `thanos-receive-internal-nlb.example.local` | Thanos Receive internal NLB DNS |

RDS is intentionally deferred. Its endpoint placeholder and credentials still
require a separate follow-up deployment.

## Important

- Do not push YAML files to ECR. ECR stores container images only.
- Argo CD reads YAML/Helm values from Git.
- Frontend and backend are in the same `stock-demo` namespace. The frontend can
  call the backend with the Kubernetes DNS name `http://backend:8000`.
- Service VPC agents cannot use `*.svc.cluster.local` addresses from the ops cluster.
  They need internal NLB DNS names for Loki and Thanos Receive.
