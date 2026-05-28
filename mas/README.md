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
  Dockerfile
  requirements.txt
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
3. Add a new item to `mas_agents` in `ansible/group_vars/all.yml`.
4. If the agent needs AWS permissions, add a dedicated role or policy in `vpc/ops/mas.tf`.
5. Rebuild and push the agent image, then run the Ansible bootstrap.

For example, a future planner pod would usually add:

```text
mas/app/agents/planner.py
ansible/group_vars/all.yml -> mas_agents item named mas-planner-agent
vpc/ops/mas.tf -> Pod Identity role/policy for mas-planner-agent
```
