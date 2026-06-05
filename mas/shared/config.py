import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_name: str
    agent_role: str
    aws_region: str
    bedrock_model_id: str | None
    bedrock_max_tokens: int
    bedrock_temperature: float
    prometheus_url: str
    orchestrator_url: str
    observer_url: str
    analyzer_url: str
    temporal_host: str
    temporal_namespace: str
    temporal_orchestrator_task_queue: str
    temporal_observer_task_queue: str
    temporal_analyzer_task_queue: str


def load_settings() -> Settings:
    return Settings(
        service_name=os.getenv("MAS_SERVICE_NAME", "mas-runtime"),
        agent_role=os.getenv("MAS_AGENT_ROLE", "runtime"),
        aws_region=os.getenv("AWS_REGION", "ap-northeast-2"),
        bedrock_model_id=os.getenv("BEDROCK_MODEL_ID"),
        bedrock_max_tokens=int(os.getenv("BEDROCK_MAX_TOKENS", "1000")),
        bedrock_temperature=float(os.getenv("BEDROCK_TEMPERATURE", "0.2")),
        prometheus_url=os.getenv(
            "PROMETHEUS_URL",
            "http://prometheus-server.monitoring.svc.cluster.local",
        ),
        orchestrator_url=os.getenv(
            "MAS_ORCHESTRATOR_URL",
            "http://mas-orchestrator.mas.svc.cluster.local:8080",
        ),
        observer_url=os.getenv(
            "MAS_OBSERVER_URL",
            "http://mas-observer-agent.mas.svc.cluster.local:8080",
        ),
        analyzer_url=os.getenv(
            "MAS_ANALYZER_URL",
            "http://mas-analyzer-agent.mas.svc.cluster.local:8080",
        ),
        temporal_host=os.getenv(
            "TEMPORAL_HOST",
            "temporal-frontend.temporal-system.svc.cluster.local:7233",
        ),
        temporal_namespace=os.getenv("TEMPORAL_NAMESPACE", "mas"),
        temporal_orchestrator_task_queue=os.getenv("TEMPORAL_ORCHESTRATOR_TASK_QUEUE", "mas-orchestrator"),
        temporal_observer_task_queue=os.getenv("TEMPORAL_OBSERVER_TASK_QUEUE", "mas-observer-agent"),
        temporal_analyzer_task_queue=os.getenv("TEMPORAL_ANALYZER_TASK_QUEUE", "mas-analyzer-agent"),
    )
