# MAS

MAS workloads are grouped by scenario first, then by agent role.

```text
mas/
  base/
    Dockerfile
  requirements.txt
  pods/
    finops/
      ui/
        app/
          __init__.py
          main.py
        Dockerfile
        agent.yml
      orchestrator/
        .gitkeep
    gitops/
      <agent>/
    secops/
      <agent>/
```

The standard agent path is:

```text
mas/pods/<scenario>/<agent>/
```

For example:

```text
mas/pods/finops/ui
mas/pods/finops/orchestrator
mas/pods/secops/analyzer
mas/pods/gitops/ui
```

## Agent Files

Each deployable agent needs:

```text
mas/pods/<scenario>/<agent>/
  app/
    __init__.py
    main.py
  Dockerfile
  agent.yml
```

`app/main.py` contains the FastAPI server or agent runtime code.

`app/__init__.py` makes `app` importable by Python, so the container can run:

```text
uvicorn app.main:app
```

`Dockerfile` builds the agent image by using the MAS base image and copying only
that agent's app code.

`agent.yml` is the CI/CD contract. GitHub Actions reads it to decide which ECR
repo to use, which Dockerfile to build, and which internal GitOps manifest to
update.

## Current FinOps UI

The FinOps UI agent is now:

```text
mas/pods/finops/ui
```

Its deployment name remains:

```text
finops-ui
```

That name is defined in:

```text
mas/pods/finops/ui/agent.yml
```

Current image repository:

```text
financial/mas/finops/ui
```

## GitHub Actions Impact

The MAS deploy workflow uses the nested path format:

```text
.github/workflows/mas-agent-deploy.yml
```

Manual input examples:

```text
operation: new
agent: finops/ui
deploy_scope: full
```

```text
operation: update
agent: finops/ui
deploy_scope: full
```

```text
operation: all
deploy_scope: full
```

`operation: all` scans:

```text
mas/pods/*/*/agent.yml
```

So future agents such as these are detected automatically after they have an
`agent.yml` and `Dockerfile`:

```text
mas/pods/finops/orchestrator/agent.yml
mas/pods/secops/analyzer/agent.yml
mas/pods/gitops/ui/agent.yml
```

For backward compatibility, the workflow can resolve `finops-ui` to `finops/ui`
when that nested path exists. The preferred input is still `finops/ui`.

## Image Build Impact

Base image:

```text
financial/mas/base
```

Agent image:

```text
financial/mas/<scenario>/<agent>
```

For the FinOps UI:

```text
financial/mas/finops/ui
```

The FinOps UI Dockerfile now copies:

```dockerfile
COPY pods/finops/ui/app ./app
```

Because the Docker build context is still:

```text
mas
```

## GitOps Manifest Impact

The Kubernetes workload name can stay `finops-ui`, but the image repository in
the GitOps kustomization must match the new ECR path:

```text
gitops/platform/financial-ops-eks/finops-mas/kustomization.yaml
```

Image entry:

```yaml
images:
  - name: finops-ui-image
    newName: REPLACE_WITH_ECR_REGISTRY/financial/mas/finops/ui
    newTag: latest
```

The namespace remains:

```text
finops-mas
```

The service remains:

```text
finops-ui
```

So the access command is unchanged:

```text
kubectl -n finops-mas port-forward svc/finops-ui 18080:80
```

## Adding Another FinOps Agent

For a future orchestrator:

```text
mas/pods/finops/orchestrator/
  app/
    __init__.py
    main.py
  Dockerfile
  agent.yml
```

Example `agent.yml`:

```yaml
name: finops-orchestrator
scenario: finops
role: orchestrator
image_repository: financial/mas/finops/orchestrator
base_image_repository: financial/mas/base
dockerfile: mas/pods/finops/orchestrator/Dockerfile
build_context: mas
namespace: finops-mas
target_cluster: financial-ops-eks
```

## Teleport App Service

The Teleport Application Service agent lives in:

```text
mas/pods/platform/teleport-app-service
```

It builds a private ECR mirror/wrapper image for the Teleport app-service
runtime:

```text
financial/mas/platform/teleport-app-service
```

The GitOps manifests live in:

```text
gitops/platform/financial-ops-eks/teleport-app-service
```

This app-service runs inside the Ops EKS cluster and registers MAS dashboard
apps with the VPC3 Teleport cluster. The first registered app is:

```text
finops-ui -> http://finops-ui.finops-mas.svc.cluster.local
```

To build and deploy it through the MAS workflow:

```text
operation: new
agent: platform/teleport-app-service
deploy_scope: full
```

After a destroy/apply, `financial-gitops-bootstrap` syncs these manifests into
the internal GitOps repository. Terraform generates the Teleport app join token,
VPC3 Teleport accepts that token, and the GitOps bootstrap creates the matching
Kubernetes Secret in `teleport-apps`.
