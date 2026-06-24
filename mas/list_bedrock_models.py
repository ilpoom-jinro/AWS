import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boto3

region = os.getenv("AWS_REGION", "ap-northeast-2")
# 주의: 'bedrock' (컨트롤플레인) — 'bedrock-runtime' 아님
bedrock = boto3.client("bedrock", region_name=region)
print(f"=== Region: {region} ===\n")

print("[Inference Profiles] — 보통 이 ID를 modelId로 씀 (apac. 프리픽스 주목)")
try:
    for p in bedrock.list_inference_profiles().get("inferenceProfileSummaries", []):
        if "claude" in p["inferenceProfileId"].lower():
            print(f"  {p['inferenceProfileId']}   ({p.get('status')})")
except Exception as e:
    print("  조회 실패:", e)

print("\n[Foundation Models] — Claude, ON_DEMAND 지원 여부")
try:
    for m in bedrock.list_foundation_models().get("modelSummaries", []):
        if "claude" in m["modelId"].lower():
            types = ",".join(m.get("inferenceTypesSupported", []))
            print(f"  {m['modelId']:55} [{types}]")
except Exception as e:
    print("  조회 실패:", e)