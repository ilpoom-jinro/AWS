"""
규정 .md 파일들을 Bedrock KB 데이터 소스용 S3 버킷에 업로드.

사전: MFA 세션 자격증명 + 대상 리전(ap-northeast-2).
실행 (mas/ 에서):
    python deploy/kb/upload_regulations.py --bucket <SOURCE_BUCKET> [--prefix regulations/]

버킷이 없으면 생성한다. 이후 Bedrock KB 데이터 소스가 s3://<bucket>/<prefix> 를 가리키게 하고 Sync.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REG_DIR = Path(__file__).resolve().parents[2] / "pods/secops/orchestrator/app/regulations"


def ensure_bucket(s3, bucket: str, region: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"[ok] 버킷 존재: {bucket}")
    except ClientError:
        kwargs = {"Bucket": bucket}
        if region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**kwargs)
        print(f"[created] 버킷 생성: {bucket} ({region})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True, help="규정 문서를 담을 S3 버킷명")
    ap.add_argument("--prefix", default="regulations/", help="객체 키 프리픽스")
    ap.add_argument("--region", default="ap-northeast-2")
    args = ap.parse_args()

    files = sorted(REG_DIR.glob("*.md"))
    if not files:
        sys.exit(f"규정 파일 없음: {REG_DIR}")

    s3 = boto3.client("s3", region_name=args.region)
    ensure_bucket(s3, args.bucket, args.region)
    for f in files:
        key = f"{args.prefix}{f.name}"
        s3.upload_file(str(f), args.bucket, key)
        print(f"[up] s3://{args.bucket}/{key}")
    print(f"\n완료 — {len(files)}개. KB 데이터 소스를 s3://{args.bucket}/{args.prefix} 로 설정 후 Sync.")


if __name__ == "__main__":
    main()
