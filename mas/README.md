# MAS

Multi-agent system workloads are grouped by scenario.

```text
mas/
  base/
  pods/
    finops/
      ui/
    gitops/
    secops/
```

Each agent lives under:

```text
mas/pods/<scenario>/<agent>/
  app/
    __init__.py
    main.py
  Dockerfile
  agent.yml
```

For example, the FinOps UI agent lives in:

```text
mas/pods/finops/ui
```

The Kubernetes/ECR name can still be scenario-qualified through `agent.yml`.
