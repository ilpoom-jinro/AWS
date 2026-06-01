# financial-ops-eks

Target cluster for resources in the internal ops VPC.

This cluster should run:

- Grafana
- Loki
- Thanos Receive/Query
- Alertmanager
- Ops VPC observability agent

Monitoring workloads should be scheduled onto the monitoring node group with:

- `nodeSelector: role=monitoring`
- `toleration: dedicated=monitoring:NoSchedule`

The application backend is not deployed here. It runs in `financial-service-eks`.
