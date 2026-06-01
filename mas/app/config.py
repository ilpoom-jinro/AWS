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
    observer_url: str
    analyzer_url: str


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
        observer_url=os.getenv(
            "MAS_OBSERVER_URL",
            "http://mas-observer-agent.mas.svc.cluster.local:8080",
        ),
        analyzer_url=os.getenv(
            "MAS_ANALYZER_URL",
            "http://mas-analyzer-agent.mas.svc.cluster.local:8080",
        ),
    )
