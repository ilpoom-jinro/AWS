# ──────────────────────────────────────────────────────────────────────────────
# SecOps KB 규정 데이터 소스 버킷 — 지속 레이어 (destroy 주기 밖)
#
# Bedrock Knowledge Base(S3 Vectors)의 데이터 소스. 규정 원본(.md)이 여기 들어간다.
# 정적 참조 데이터라 destroy/apply와 무관하게 유지되어야 하므로 velero/teleport 데이터와
# 동일하게 bootstrap state에 배치. 벡터 스토어(S3 Vectors)는 Bedrock Quick Create가
# 별도 생성하므로 여기엔 데이터 소스 버킷만 둔다.
#
# 사용:
#   업로드) mas/deploy/kb/upload_regulations.py \
#             --bucket financial-secops-kb-regulations-<account_id> --prefix regulations/
#   KB)     Bedrock 콘솔 Quick Create 데이터 소스 = s3://<이 버킷>/regulations/
#
# ⚠️ 이 버킷은 SSE-KMS(key-s3 CMK)로 암호화되므로, KB 생성 시 만들어지는 Bedrock
#    서비스 역할에 이 CMK에 대한 kms:Decrypt를 부여해야 Sync가 문서를 읽을 수 있다.
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "secops_kb_regulations" {
  bucket        = "financial-secops-kb-regulations-${data.aws_caller_identity.current.account_id}"
  force_destroy = false # 규정 코퍼스 실수 삭제 방지

  tags = {
    Name               = "financial-secops-kb-regulations"
    DataClassification = "Internal"
  }
}

resource "aws_s3_bucket_versioning" "secops_kb_regulations" {
  bucket = aws_s3_bucket.secops_kb_regulations.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "secops_kb_regulations" {
  bucket = aws_s3_bucket.secops_kb_regulations.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = data.aws_kms_alias.key_s3.target_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "secops_kb_regulations" {
  bucket                  = aws_s3_bucket.secops_kb_regulations.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "secops_kb_regulations" {
  bucket = aws_s3_bucket.secops_kb_regulations.id

  rule {
    id     = "hygiene"
    status = "Enabled"
    filter { prefix = "" }

    # 규정은 정적 참조 데이터 → 오브젝트 만료 없음. 미완료 업로드·구버전만 정리.
    abort_incomplete_multipart_upload {
      days_after_initiation = 2
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  depends_on = [aws_s3_bucket_versioning.secops_kb_regulations]
}

output "secops_kb_regulations_bucket" {
  description = "SecOps KB 규정 데이터 소스 버킷명 (upload_regulations.py --bucket 인자)"
  value       = aws_s3_bucket.secops_kb_regulations.bucket
}
