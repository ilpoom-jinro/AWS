data "aws_caller_identity" "current" {}

# 루트 모듈의 key-s3 참조 (루트 apply 후 bootstrap re-apply 시 사용 가능)
data "aws_kms_alias" "key_s3" {
  name = "alias/key-s3"
}

# ─────────────────────────────────────
# Terraform State S3 버킷
# ─────────────────────────────────────
resource "aws_s3_bucket" "terraform_state" {
  bucket = "ilpumjinro-terraform-state-v3"
  lifecycle {
    prevent_destroy = true
  }
  tags = {
    Name      = "ilpumjinro-terraform-state-v3"
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Purpose   = "terraform-state"
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms" # aws/s3 기본키 대신 CMK 사용
      kms_master_key_id = data.aws_kms_alias.key_s3.target_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# ─────────────────────────────────────
# CloudTrail 로그 S3 버킷 (Object Lock)
# ─────────────────────────────────────
resource "aws_s3_bucket" "cloudtrail_logs_locked" {
  bucket              = "ilpumjinro-cloudtrail-logs-locked-v3"
  object_lock_enabled = true
  lifecycle {
    # #12 로그 장기보존 — 버킷 실수 삭제 방지
    prevent_destroy = true
  }
  tags = {
    Name      = "ilpumjinro-cloudtrail-logs-locked-v3"
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Purpose   = "cloudtrail-logs-immutable"
  }
}

resource "aws_s3_bucket_versioning" "cloudtrail_logs_locked" {
  bucket = aws_s3_bucket.cloudtrail_logs_locked.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail_logs_locked" {
  bucket = aws_s3_bucket.cloudtrail_logs_locked.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms" # aws/s3 기본키 대신 CMK 사용
      kms_master_key_id = data.aws_kms_alias.key_s3.target_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail_logs_locked" {
  bucket                  = aws_s3_bucket.cloudtrail_logs_locked.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_object_lock_configuration" "cloudtrail_logs_locked" {
  bucket = aws_s3_bucket.cloudtrail_logs_locked.id
  rule {
    default_retention {
      # #12 로그 장기보존 — 학습 환경이라 GOVERNANCE, prod에선 COMPLIANCE 전환 예정
      mode = "GOVERNANCE"
      days = 365
    }
  }
}

# CloudTrail 버킷 — Object Lock 365일이 이미 보존·무결성 담당
# lifecycle은 잠금 풀린 뒤 무한 누적만 막으면 됨
resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail_logs_locked" {
  bucket = aws_s3_bucket.cloudtrail_logs_locked.id
  rule {
    id     = "expire-after-lock"
    status = "Enabled"
    filter { prefix = "" }
    expiration { days = 370 } # 365일 잠금 직후 삭제 → 보존 1년 캡, 누적 방지
  }
}

resource "aws_s3_bucket_policy" "cloudtrail_logs_locked" {
  bucket = aws_s3_bucket.cloudtrail_logs_locked.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AWSCloudTrailAclCheck"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action   = "s3:GetBucketAcl"
        Resource = "arn:aws:s3:::ilpumjinro-cloudtrail-logs-locked-v3"
      },
      {
        Sid    = "AWSCloudTrailWrite"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action   = "s3:PutObject"
        Resource = "arn:aws:s3:::ilpumjinro-cloudtrail-logs-locked-v3/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl" = "bucket-owner-full-control"
          }
        }
      }
    ]
  })
}