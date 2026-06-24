import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared.bedrock import ClaudeModel, get_bedrock_client

model_id = os.getenv("BEDROCK_MODEL", ClaudeModel.HAIKU.value)
client = get_bedrock_client()
resp = client.converse(
    modelId=model_id,
    messages=[{"role": "user", "content": [{"text": "한 단어로 답해: 작동하나?"}]}],
    inferenceConfig={"maxTokens": 50, "temperature": 0},
)
print("MODEL:", model_id)
print("REPLY:", resp["output"]["message"]["content"][0]["text"])
print("USAGE:", resp.get("usage"))