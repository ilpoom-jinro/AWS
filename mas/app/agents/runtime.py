from typing import Any

from app.agents.analyzer import AnalyzerAgent
from app.agents.observer import ObserverAgent


class RuntimeAgent:
    def __init__(self, observer: ObserverAgent, analyzer: AnalyzerAgent) -> None:
        self.observer = observer
        self.analyzer = analyzer

    async def analyze_namespace(self, namespace: str, prompt: str | None = None) -> dict[str, Any]:
        signals = await self.observer.collect_namespace_signals(namespace)
        analysis = self.analyzer.analyze_signals(namespace, signals, prompt)
        return {
            "namespace": namespace,
            "signals": signals,
            "analysis": analysis,
        }
