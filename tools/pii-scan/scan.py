#!/usr/bin/env python3
"""S3 객체를 Presidio로 스캔해 PII 소재를 탐지하고, 결과를 OCSF JSON으로 S3에 적재.
- CodeBuild(NO_SOURCE)에서 실행. 대상/결과 버킷은 환경변수로 주입.
- 실제 PII 값은 저장하지 않음(타입·위치·신뢰도만) → 결과 버킷의 2차 PII 적재 방지."""
import os
import json
import datetime
import uuid

import boto3
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import EmailRecognizer, CreditCardRecognizer
from kr_recognizers import (
    KrRrnRecognizer,
    build_phone_recognizer,
    build_biz_reg_recognizer,
    build_account_recognizer,
)

# ── 환경변수 (CodeBuild environment_variable로 주입) ──────────
TARGET_BUCKETS = [b.strip() for b in os.environ.get("TARGET_BUCKETS", "").split(",") if b.strip()]
FINDINGS_BUCKET = os.environ["FINDINGS_BUCKET"]
REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-2")

# 텍스트로 취급할 확장자만 스캔 (바이너리/대용량 스킵)
TEXT_EXT = (".txt", ".csv", ".json", ".log", ".md", ".tsv", ".yaml", ".yml")
MAX_BYTES = 5 * 1024 * 1024  # 객체당 5MB 상한 (PoC 안전장치)

s3 = boto3.client("s3")


def build_analyzer():
    """한국어 NER + 한국 커스텀 인식기 + 필요한 내장 인식기로 Analyzer 구성."""
    # ko_core_news_md: 이름·주소·기관명 등 비정형 PII 탐지용 NER
    nlp_engine = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "ko", "model_name": "ko_core_news_md"}],
    }).create_engine()

    registry = RecognizerRegistry()
    # 한국 정형 PII
    registry.add_recognizer(KrRrnRecognizer())            # 주민번호 (체크섬)
    registry.add_recognizer(build_phone_recognizer())     # 휴대전화
    registry.add_recognizer(build_biz_reg_recognizer())   # 사업자등록번호
    registry.add_recognizer(build_account_recognizer())   # 계좌번호
    # 내장 인식기를 한국어(ko)로도 등록 (기본 en이라 ko 분석 시 누락됨)
    registry.add_recognizer(CreditCardRecognizer(supported_language="ko"))  # Luhn 내장
    registry.add_recognizer(EmailRecognizer(supported_language="ko"))

    return AnalyzerEngine(nlp_engine=nlp_engine, registry=registry, supported_languages=["ko"])


def iter_text_objects(bucket):
    """버킷의 텍스트 객체를 (key, text)로 순회."""
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.lower().endswith(TEXT_EXT) or obj["Size"] > MAX_BYTES:
                continue
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            try:
                yield key, body.decode("utf-8")
            except UnicodeDecodeError:
                continue  # 디코딩 불가 객체 스킵


def to_ocsf(bucket, key, rec, now_ms):
    """Presidio 탐지 1건 → OCSF Data Security Finding(class_uid 2006) 최소 레코드.
    ※ 정확한 OCSF 스키마 버전·필드는 MAS 단계에서 Prowler OCSF 출력과 정렬할 것."""
    return {
        "activity_id": 1,
        "category_uid": 2,            # Findings
        "class_uid": 2006,            # Data Security Finding
        "type_uid": 200601,
        "time": now_ms,
        "severity_id": 3,             # Medium (PoC 고정)
        "metadata": {"version": "1.1.0",
                     "product": {"name": "Presidio", "vendor_name": "Microsoft"}},
        "finding_info": {"uid": str(uuid.uuid4()),
                         "title": f"PII detected: {rec['entity_type']}"},
        "resources": [{"type": "S3 Object", "uid": f"s3://{bucket}/{key}"}],
        "unmapped": {                 # 비표준 보조 필드 (값 아닌 위치/타입만)
            "entity_type": rec["entity_type"], "score": rec["score"],
            "start": rec["start"], "end": rec["end"],
        },
    }


def main():
    analyzer = build_analyzer()
    now = datetime.datetime.utcnow()
    now_ms = int(now.timestamp() * 1000)
    date_prefix = now.strftime("%Y-%m-%d")

    raw_findings, ocsf_findings = [], []
    for bucket in TARGET_BUCKETS:
        for key, text in iter_text_objects(bucket):
            for r in analyzer.analyze(text=text, language="ko"):
                rec = {"bucket": bucket, "key": key, "entity_type": r.entity_type,
                       "score": round(r.score, 3), "start": r.start, "end": r.end}
                raw_findings.append(rec)
                ocsf_findings.append(to_ocsf(bucket, key, rec, now_ms))

    # 결과 적재 (KMS 암호화는 버킷 기본 SSE-KMS로 자동 적용 → 코드에서 별도 지정 불필요)
    base = f"{date_prefix}/pii-scan-{now.strftime('%H%M%S')}"
    s3.put_object(Bucket=FINDINGS_BUCKET, Key=f"{base}.raw.json",
                  Body=json.dumps(raw_findings, ensure_ascii=False, indent=2).encode("utf-8"),
                  ContentType="application/json")
    s3.put_object(Bucket=FINDINGS_BUCKET, Key=f"{base}.ocsf.json",
                  Body=json.dumps(ocsf_findings, ensure_ascii=False).encode("utf-8"),
                  ContentType="application/json")
    print(f"[done] buckets={len(TARGET_BUCKETS)} findings={len(raw_findings)}")
    print(f"[done] s3://{FINDINGS_BUCKET}/{base}.ocsf.json")


if __name__ == "__main__":
    main()
