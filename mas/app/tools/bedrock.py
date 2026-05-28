import os
from typing import Any

import boto3


class BedrockConfigError(RuntimeError):
    pass


class BedrockClient:
    def __init__(
        self,
        region: str,
        model_id: str,
        max_tokens: int = 1000,
        temperature: float = 0.2,
    ) -> None:
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.client = boto3.client("bedrock-runtime", region_name=region)

    @classmethod
    def from_env(cls) -> "BedrockClient":
        region = os.getenv("AWS_REGION", "ap-northeast-2")
        model_id = os.getenv("BEDROCK_MODEL_ID")
        if not model_id:
            raise BedrockConfigError("BEDROCK_MODEL_ID is not configured")
        return cls(
            region=region,
            model_id=model_id,
            max_tokens=int(os.getenv("BEDROCK_MAX_TOKENS", "1000")),
            temperature=float(os.getenv("BEDROCK_TEMPERATURE", "0.2")),
        )

    def converse(self, prompt: str) -> dict[str, Any]:
        response = self.client.converse(
            modelId=self.model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            inferenceConfig={
                "maxTokens": self.max_tokens,
                "temperature": self.temperature,
            },
        )
        return response.get("output", {})
