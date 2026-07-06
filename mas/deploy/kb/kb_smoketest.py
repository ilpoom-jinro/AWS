"""
Bedrock KB 스모크 테스트 — retrieve가 규정을 돌려주는지 확인.

사전: MFA 세션 자격증명 + KB 생성/Sync 완료.
실행 (mas/ 에서):
    $env:BEDROCK_KB_ID="XXXXXXXX"
    python deploy/kb/kb_smoketest.py "비정상 외부 송신 트래픽 데이터 유출"
"""

from __future__ import annotations

import os
import sys

import boto3


def main() -> None:
    kb_id = os.getenv("BEDROCK_KB_ID")
    if not kb_id:
        sys.exit("BEDROCK_KB_ID 미설정")
    query = sys.argv[1] if len(sys.argv) > 1 else "비정상 외부 송신 트래픽 데이터 유출"
    region = os.getenv("AWS_REGION", "ap-northeast-2")

    client = boto3.client("bedrock-agent-runtime", region_name=region)
    resp = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}},
    )
    results = resp.get("retrievalResults", [])
    print(f"query: {query}\nKB: {kb_id} ({region}) — {len(results)}개 결과\n")
    for i, r in enumerate(results, 1):
        uri = r.get("location", {}).get("s3Location", {}).get("uri", "")
        score = r.get("score", 0.0)
        text = r.get("content", {}).get("text", "")[:200].replace("\n", " ")
        print(f"[{i}] score={score:.3f} {uri}\n    {text}\n")
    if not results:
        print("결과 없음 — Sync 완료 여부 / 쿼리 / KB_ID 확인")


if __name__ == "__main__":
    main()
