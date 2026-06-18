"""
Bedrock SDK 퍼블릭
"""

from shared.bedrock.client import ClaudeModel, get_bedrock_client

__all__ = [
    "get_bedrock_client",
    "ClaudeModel",
]