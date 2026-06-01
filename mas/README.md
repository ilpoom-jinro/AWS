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
  pods/
    orchestrator/
      Dockerfile            # FROM mas-base, adds orchestrator code
      agent.yml             # Kubernetes deployment config for this pod
    observer/
      Dockerfile            # FROM mas-base, adds observer code
      agent.yml             # Kubernetes deployment config for this pod
    analyzer/
      Dockerfile            # FROM mas-base, adds analyzer code
      agent.yml             # Kubernetes deployment config for this pod
  app/
    main.py                 # all-in-one local/dev API entrypoint
    config.py               # environment-driven runtime settings
    agents/                 # role-specific agent code
      orchestrator.py       # calls observer and analyzer services
      observer.py           # reads Prometheus/Kubernetes signals
      analyzer.py           # calls Bedrock and explains signals
    entrypoints/            # role-specific FastAPI apps used by images
      orchestrator.py
      observer.py
      analyzer.py
    tools/                  # external systems used by agents
      bedrock.py
      kubernetes.py
      prometheus.py
```

## Add a New Agent Pod

1. Add agent code under `mas/app/agents/<agent_name>.py`.
2. Add shared integrations under `mas/app/tools/` if needed.
3. Add a pod folder under `mas/pods/<agent_name>/`.
4. Add `mas/pods/<agent_name>/agent.yml` for Kubernetes deployment config.
5. Add `mas/pods/<agent_name>/Dockerfile` if the agent needs a dedicated image.
6. If the agent needs AWS permissions, add a dedicated role or policy in `vpc/ops/mas-<agent_name>.tf`.
7. Rebuild and push the agent image, then run the Ansible bootstrap.

For example, a future planner pod would usually add:

```text
mas/app/agents/planner.py
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
```

## CI/CD

`.github/workflows/mas-deploy.yml` is the MAS deployment path.

On changes to `mas/**`, MAS Ansible files, or MAS Terraform files, it:

1. validates Terraform and compiles MAS Python sources,
2. applies the MAS and Ansible CodeBuild ECR repositories,
3. builds and pushes `financial/mas-base:latest` and the agent images,
   `financial/mas-orchestrator:latest`, `financial/mas-observer:latest`,
   and `financial/mas-analyzer:latest`,
4. rebuilds `financial/ansible-codebuild:latest` so the latest Ansible templates are baked in,
5. applies the MAS Bedrock endpoints, Pod Identity role, and CodeBuild runtime config,
6. starts `financial-ansible-bootstrap` for initial platform bootstrap. The bootstrap writes
   MAS manifests into the internal GitOps repository and Argo CD deploys them to the `mas`
   namespace.

`.github/workflows/mas-update.yml` is the MAS update path. It rebuilds the MAS images,
rebuilds the Ansible CodeBuild image, and starts `financial-mas-gitops-sync`. That CodeBuild
updates `apps/mas/mas.yaml` in the internal GitOps repository, then Argo CD syncs the change.

`.github/workflows/mas-analyze.yml` is the first operator-facing analysis path. It accepts a
namespace and prompt, starts `financial-mas-analyze`, port-forwards to `mas-orchestrator`
inside the Ops EKS cluster, calls `/analyze`, and prints the JSON result in the CodeBuild log.

That means a normal agent change should usually touch only:

```text
mas/app/agents/<agent_name>.py
mas/app/tools/<tool_name>.py
mas/pods/<agent_name>/agent.yml
vpc/ops/mas-<agent_name>.tf
```

The current Bedrock permission lives in:

```text
vpc/ops/mas-analyzer.tf
```
