# MAS Agent Pod Structure

MAS agent pod는 네 가지 조각으로 구성합니다.

```text
base image = Python runtime + shared dependencies
agent image = base image + role-specific app code
Kubernetes Deployment = run the image on EKS
ServiceAccount/IAM = what the pod can do in AWS/Kubernetes
Config = what role this agent performs
```

## Folders

```text
mas/
  requirements.txt
  base/
    Dockerfile              # shared runtime and Python dependencies
  shared/                   # common config, schemas, and external integrations
    config.py
    schemas.py
    tools/
      bedrock.py
      kubernetes.py
      prometheus.py
  pods/
    orchestrator/
      app/                  # orchestrator FastAPI app and role code
        main.py
        agent.py
      Dockerfile            # FROM mas-base, adds shared + orchestrator code
      agent.yml             # Kubernetes deployment config for this pod
    observer/
      app/                  # observer FastAPI app and role code
        main.py
        agent.py
      Dockerfile            # FROM mas-base, adds shared + observer code
      agent.yml             # Kubernetes deployment config for this pod
    analyzer/
      app/                  # analyzer FastAPI app and role code
        main.py
        agent.py
      Dockerfile            # FROM mas-base, adds shared + analyzer code
      agent.yml             # Kubernetes deployment config for this pod
    ui/
      app/                  # operator chat UI FastAPI app
        main.py
      Dockerfile            # FROM mas-base, adds shared + UI code
      agent.yml             # Kubernetes deployment config for the UI pod
```

## Add a New Agent Pod

1. Add a pod folder under `mas/pods/<agent_name>/`.
2. Add role-specific code under `mas/pods/<agent_name>/app/`.
3. Add shared integrations under `mas/shared/tools/` if needed.
4. Add `mas/pods/<agent_name>/agent.yml` for Kubernetes deployment config.
5. Add `image_repository: financial/mas-<agent_name>` to `agent.yml`.
6. Add `mas/pods/<agent_name>/Dockerfile`.
7. If the agent needs AWS permissions, add a dedicated role or policy in `vpc/ops/mas-<agent_name>.tf`.
8. Push the change and run the MAS update or deploy workflow.

For example, a future planner pod would usually add:

```text
mas/pods/planner/app/agent.py
mas/pods/planner/app/main.py
mas/pods/planner/agent.yml
mas/pods/planner/Dockerfile
vpc/ops/mas-planner.tf
```

With the current layout, that becomes:

```text
mas/pods/planner/app/main.py
mas/pods/planner/app/agent.py
mas/pods/planner/agent.yml
mas/pods/planner/Dockerfile
vpc/ops/mas-planner.tf
```

## Current Pod Split

```text
mas-orchestrator
  POST /analyze
  -> calls mas-observer-agent /observe
  -> calls mas-analyzer-agent /analyze-signals

mas-observer-agent
  POST /observe
  -> reads Prometheus and Kubernetes
  -> returns structured signals

mas-analyzer-agent
  POST /analyze-signals
  -> calls Bedrock Runtime
  -> returns analysis

mas-ui
  GET /
  -> shows a small internal chat UI
  POST /api/chat
  -> forwards the prompt to mas-orchestrator /analyze
```

## CI/CD

`.github/workflows/mas-deploy.yml` is the MAS deployment path.

On changes to `mas/**`, MAS Ansible files, or MAS Terraform files, it:

1. validates Terraform and compiles MAS Python sources,
2. creates missing MAS and Ansible CodeBuild ECR repositories,
3. builds and pushes `financial/mas-base:latest` and every image declared under
   `mas/pods/*/agent.yml`,
4. rebuilds `financial/ansible-codebuild:latest` so the latest Ansible templates are baked in,
5. applies the MAS Bedrock endpoints, Pod Identity role, and CodeBuild runtime config,
6. starts `financial-ansible-bootstrap` for initial platform bootstrap. The bootstrap writes
   MAS manifests into the internal GitOps repository and Argo CD deploys them to the `mas`
   namespace.

The same `.github/workflows/mas-deploy.yml` workflow is also the MAS update path. On MAS
changes it rebuilds the MAS images and starts `financial-mas-gitops-sync`. That CodeBuild
updates `apps/mas/mas.yaml` in the internal GitOps repository, then Argo CD syncs the change.

`.github/workflows/mas-analyze.yml` is the first operator-facing analysis path. It accepts a
namespace and prompt, starts `financial-mas-analyze`, port-forwards to `mas-orchestrator`
inside the Ops EKS cluster, calls `/analyze`, and prints the JSON result in the CodeBuild log.

The UI path is `mas-ui`. It is deployed as a Kubernetes Service in the `mas` namespace and calls
`mas-orchestrator` internally. Teleport App Service support is templated but disabled by default;
enable it with `TELEPORT_APP_SERVICE_ENABLED=true` and provide the `teleport-app-join-token`
Secret before syncing MAS GitOps manifests.

That means a normal agent change should usually touch only:

```text
mas/pods/<agent_name>/app/main.py
mas/pods/<agent_name>/app/agent.py
mas/shared/tools/<tool_name>.py
mas/pods/<agent_name>/agent.yml
vpc/ops/mas-<agent_name>.tf
```

The current Bedrock permission lives in:

```text
vpc/ops/mas-analyzer.tf
```
