# Offline Helm Chart Layout

This directory is for observability Helm deployments in the disconnected EKS
environment.

## What Goes Where

| Item | Location | Notes |
|---|---|---|
| Helm chart source | `helmChart/charts/*` | Copy the official chart here from an internet-connected environment. |
| Helm values | `helmChart/*/values.yaml` | Put ECR image paths and deployment settings here. |
| Argo CD Application | `helmChart/*/application.yaml` | Tells Argo CD which chart to deploy to which cluster. |
| Container images | ECR | Images are not stored in Git. |

## Current Offline Images

The current values use the mirrored private ECR images. Loki and Alloy optional
helper containers are disabled so that they do not need public internet access.

| Workload | Private ECR repository |
|---|---|
| Grafana | `financial/monitoring/grafana` |
| Loki | `financial/monitoring/loki` |
| Thanos | `financial/monitoring/thanos` |
| Alloy | `financial/monitoring/alloy` |
| Alertmanager | `financial/monitoring/alertmanager` |
| AWS Load Balancer Controller | `financial/system/aws-load-balancer-controller` |

## Recommended Flow

1. Mirror container images to ECR.
2. Copy official Helm charts into `helmChart/charts`.
3. Replace ECR placeholders in each `values.yaml`.
4. Push this directory to the GitOps repo.
5. Let Argo CD deploy the Applications.

## Alloy Collection Rules

Each EKS cluster runs Alloy as a DaemonSet. Each Alloy pod collects data only
from its own node to avoid duplicate telemetry.

| Signal | Collection rule | Destination from ops VPC | Destination from service VPC |
|---|---|---|---|
| Pod logs | Collect logs from pods on the local node | Loki ClusterIP | Loki internal NLB DNS |
| Pod application metrics | Scrape pods annotated with `prometheus.io/scrape: "true"` and `prometheus.io/port` | Thanos Receive ClusterIP | Thanos Receive internal NLB DNS |
| Node metrics | Scrape local kubelet metrics through the Kubernetes API | Thanos Receive ClusterIP | Thanos Receive internal NLB DNS |
| Pod/container usage metrics | Scrape local cAdvisor metrics through the Kubernetes API | Thanos Receive ClusterIP | Thanos Receive internal NLB DNS |

Replace the two `.example.local` placeholders in
`helmChart/alloy-service/values.yaml` after the Loki and Thanos Receive internal
NLB DNS names are created.

## Deferred Storage

Loki currently keeps logs for seven days using its initial filesystem storage.
Long-term S3 object storage and the separate S3 Vectors AI indexing pipeline are
intentionally deferred.

## Expected Chart Copies

```text
helmChart/charts/grafana
helmChart/charts/loki
helmChart/charts/thanos
helmChart/charts/alloy
helmChart/charts/alertmanager
helmChart/charts/aws-load-balancer-controller
```

## Downloaded Chart Versions

| Chart | Version | Source |
|---|---:|---|
| Grafana | `10.5.15` | `grafana/helm-charts` |
| Loki | `7.0.0` | `grafana/helm-charts` |
| Alloy | `1.8.2` | `grafana/helm-charts` |
| Thanos | `17.3.1` | `bitnami/thanos` OCI chart |
| Alertmanager | `1.37.0` | `prometheus-community/helm-charts` |
| AWS Load Balancer Controller | `3.3.0` | `aws/eks-charts` |
