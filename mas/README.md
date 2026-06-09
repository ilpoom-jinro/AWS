# MAS

Multi-agent system workloads for the financial platform.

Current first slice:

- `pods/finops-ui`: FinOps dashboard and chat entrypoint for operators.

The UI runs as a FastAPI app and is intended to be deployed into
`financial-ops-eks` through GitOps.

## Agent Deployment Contract

Each deployable agent lives under `mas/pods/<agent-name>` and must include:

```text
mas/pods/<agent-name>/
  app/
  Dockerfile
  agent.yml
```

`agent.yml` is the source of truth for the generic MAS deploy workflow:

```yaml
name: finops-ui
scenario: finops
role: ui
image_repository: financial/mas/finops-ui
base_image_repository: financial/mas/base
dockerfile: mas/pods/finops-ui/Dockerfile
build_context: mas
manifest_path: financial-ops-eks/finops-mas/kustomization.yaml
target_container: finops-ui-image
service_account_name: finops-ui
service_name: finops-ui
namespace: finops-mas
target_cluster: financial-ops-eks
```

The `MAS Agent Deploy` GitHub Actions workflow reads this file, creates the ECR
repository if needed, builds and pushes the image, then starts the manifest
updater CodeBuild project. The CodeBuild job updates the image entry identified
by `target_container` inside `manifest_path` in the internal GitOps repository.

## Base Image

The common runtime lives in:

```text
mas/base/Dockerfile
mas/requirements.txt
```

The workflow can build and push this image separately:

```text
operation: base
```

The base image is pushed to:

```text
financial/mas/base
```

Agent Dockerfiles should use the base image through a build arg:

```dockerfile
ARG MAS_BASE_IMAGE=python:3.12-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app
COPY pods/<agent-name>/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

During CI/CD, the workflow passes:

```text
MAS_BASE_IMAGE=<account>.dkr.ecr.<region>.amazonaws.com/financial/mas/base:latest
```

The workflow has two control fields:

- `operation`
  - `base`: build and push only the MAS base image.
  - `new`: create missing internal GitOps manifests for one agent, then deploy it with the current ECR base image.
  - `update`: deploy one existing agent and require its internal GitOps manifest to already exist.
  - `all`: deploy every agent under `mas/pods` using the current base image.
- `deploy_scope`
  - `full`: generate allowed missing manifests, build and push the image, then update the image tag.
  - `manifests-only`: create or validate manifests without building an image.
  - `image-only`: build and push the image, then update an existing manifest only.

Typical choices:

```text
Base image only:
  operation: base

New agent:
  operation: new
  agent: <agent-name>
  deploy_scope: full

Existing agent code change:
  operation: update
  agent: <agent-name>
  deploy_scope: full

Deploy every agent:
  operation: all
  deploy_scope: full
```

Base image rebuilds are intentionally explicit. Use `operation: base` when
`mas/base/Dockerfile` or `mas/requirements.txt` changes. `new`, `update`, and
`all` do not rebuild the base image; they pull the current ECR base image and
use it through the `MAS_BASE_IMAGE` Docker build arg.

If `manifest_path` or `namespace` is omitted, the workflow derives them from
`scenario`:

```text
namespace: <scenario>-mas
manifest_path: <target_cluster>/<scenario>-mas/kustomization.yaml
```

For new scenarios, keep the same contract and choose repository/name prefixes
that match the domain, for example:

- `financial/mas/finops/<agent-name>`
- `financial/mas/gitops/<agent-name>`
- `financial/mas/secops/<agent-name>`
