from typing import Any

import httpx


class OrchestratorAgent:
    def __init__(self, observer_url: str, analyzer_url: str) -> None:
        self.observer_url = observer_url.rstrip("/")
        self.analyzer_url = analyzer_url.rstrip("/")

    async def analyze_namespace(self, namespace: str, prompt: str | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            observer_response = await client.post(
                f"{self.observer_url}/observe",
                json={"namespace": namespace},
            )
            observer_response.raise_for_status()
            observation = observer_response.json()

            analyzer_response = await client.post(
                f"{self.analyzer_url}/analyze-signals",
                json={
                    "namespace": namespace,
                    "signals": observation["signals"],
                    "prompt": prompt,
                },
            )
            analyzer_response.raise_for_status()
            analysis = analyzer_response.json()

        return {
            "namespace": namespace,
            "observation": observation,
            "analysis": analysis,
        }
