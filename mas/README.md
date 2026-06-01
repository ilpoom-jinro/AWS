# MAS Agent Pod Structure

MAS agent pod는 네 가지 조각으로 구성합니다.

```text
container image = app code + dependencies
Kubernetes Deployment = run the image on EKS
ServiceAccount/IAM = what the pod can do in AWS/Kubernetes
Config = what role this agent performs
```

## Folders

```text
mas/
  requirements.txt
  pods/
    runtime/
      Dockerfile            # container image for the runtime pod
      agent.yml             # Kubernetes deployment config for this pod
  app/
    main.py                 # API entrypoint for the current mas-runtime pod
    config.py               # environment-driven runtime settings
    agents/                 # role-specific agent code
      observer.py           # reads Prometheus/Kubernetes signals
      analyzer.py           # calls Bedrock and explains signals
      runtime.py            # composes observer + analyzer for the first pod
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

## CI/CD

`.github/workflows/mas-deploy.yml` is the MAS deployment path.

On changes to `mas/**`, MAS Ansible files, or MAS Terraform files, it:

1. validates Terraform and compiles MAS Python sources,
2. applies the MAS and Ansible CodeBuild ECR repositories,
3. builds and pushes `financial/mas-runtime:latest`,
4. rebuilds `financial/ansible-codebuild:latest` so the latest Ansible templates are baked in,
5. applies the MAS Bedrock endpoints, Pod Identity role, and CodeBuild runtime config,
6. starts `financial-ansible-bootstrap` to deploy the agent pods into the `mas` namespace.

That means a normal agent change should usually touch only:

```text
mas/app/agents/<agent_name>.py
mas/app/tools/<tool_name>.py
mas/pods/<agent_name>/agent.yml
vpc/ops/mas-<agent_name>.tf
```
