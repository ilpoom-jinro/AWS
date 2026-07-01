# ──────────────────────────────────────────────────────────────────────────────
# Teleport 세션 로그 S3 버킷
# 개발자가 VPC3 → VPC2 접근 시 세션 기록 저장
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "teleport_sessions" {
  bucket = "ilpumjinro-teleport-v4"
  lifecycle {
    # #12 로그 장기보존 — 버킷 실수 삭제 방지 (versioning은 이미 활성화)
    prevent_destroy = true
  }
  tags = {
    Name               = "ilpumjinro-teleport-v4"
    Project            = "ilpumjinro"
    ManagedBy          = "terraform"
    Purpose            = "teleport-session-logs"
    DataClassification = "Restricted"
  }
}

resource "aws_s3_bucket_versioning" "teleport_sessions" {
  bucket = aws_s3_bucket.teleport_sessions.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "teleport_sessions" {
  bucket = aws_s3_bucket.teleport_sessions.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms" # aws/s3 기본키 대신 CMK 사용
      kms_master_key_id = data.aws_kms_alias.key_s3.target_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "teleport_sessions" {
  bucket                  = aws_s3_bucket.teleport_sessions.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "teleport_sessions" {
  bucket = aws_s3_bucket.teleport_sessions.id
  rule {
    id     = "expire-old-sessions"
    status = "Enabled"
    filter {}
    expiration {
      days = 1825
    }
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}
