# financial-service-eks

Target cluster for resources in the service/globalservice VPC.

This cluster should run:

- Public-facing frontend
- Backend API
- X-Ray Collector for backend tracing
- Service VPC observability agent

The frontend and backend run in the same `stock-demo` namespace. The frontend
calls the backend through the Kubernetes internal DNS name `http://backend:8000`.

Service VPC Alloy sends logs and metrics to the monitoring tools in the ops VPC
through the Loki and Thanos Receive internal NLB DNS names.
