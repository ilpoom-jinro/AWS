# Monitoring Images

This directory keeps monitoring-specific image mirror metadata and helper scripts.

The GitHub Actions workflow `.github/workflows/monitoring-images.yml` can mirror
the images listed in `images.tsv` and build custom images listed in
`custom-images.tsv` into existing ECR repositories. Terraform does not create
those monitoring ECR repositories; create them first, then run the workflow.

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

## Mirrored Images

`images.tsv` has this format:

```text
component	source_image	ecr_repository	target_tag
```

The workflow pulls `source_image`, tags it as
`<aws-account>.dkr.ecr.<region>.amazonaws.com/<ecr_repository>:<target_tag>`,
then pushes it.

## Custom Images

`custom-images.tsv` has this format:

```text
component	dockerfile	build_context	ecr_repository	target_tag
```

To add a custom image:

1. Create the Dockerfile and related files under `monitoring/custom/<component>/`.
2. Add a row to `custom-images.tsv`.
3. Create the ECR repository named in the row.
4. Run `Mirror Monitoring Images` with `build_custom=true`.

The sample `monitoring/custom/grafana/Dockerfile` shows the expected structure
for a Grafana image with provisioning files baked in.
