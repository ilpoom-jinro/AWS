from typing import Any

from app.tools.bedrock import BedrockClient


class AnalyzerAgent:
    def __init__(self, bedrock: BedrockClient) -> None:
        self.bedrock = bedrock

    def analyze_signals(self, namespace: str, signals: dict[str, Any], prompt: str | None = None) -> dict[str, Any]:
        base_prompt = prompt or (
            "You are an internal ops assistant. Summarize these Kubernetes signals, "
            "list likely operational risks, and suggest read-only next checks. "
            "Do not suggest destructive actions."
        )
        bedrock_prompt = (
            f"{base_prompt}\n\n"
            f"Namespace: {namespace}\n"
            f"Signals: {signals}\n"
        )
        return self.bedrock.converse(bedrock_prompt)
