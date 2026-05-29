# Monitoring Images

This directory keeps monitoring-specific image mirror metadata and helper scripts.

The GitHub Actions workflow `.github/workflows/monitoring-images.yml` mirrors the
images listed in `images.tsv` into existing ECR repositories. Terraform does not
create those monitoring ECR repositories; create them first, then run the workflow.

Default ECR repositories:

- `financial/monitoring/grafana`
- `financial/monitoring/loki`
- `financial/monitoring/thanos`
- `financial/monitoring/alloy`
- `financial/monitoring/alertmanager`
- `financial/monitoring/xray-collector`
- `financial/monitoring/prometheus`

GitOps manifests for the future monitoring runtime are intentionally not stored
here yet. The monitoring control plane may move to a separate k3s runtime on the
Ops VPC monitoring subnet.
