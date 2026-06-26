# =============================================
# #18 API 호출 추적 — S3 Server Access Logging
#
# 목적: S3 버킷 접근 로그를 중앙 수집 버킷으로 모음
# source 5개:
#   - security 모듈: prowler_findings (이 파일)
#   - bootstrap: cloudtrail_logs_locked, terraform_state,
#                velero_backup, teleport_sessions
#                → bootstrap/s3_access_logging.tf에서 별도 정의
#
# ★ SSE-S3(AES256) 강제:
#   S3 log delivery 서비스는 SSE-KMS(CMK) 버킷에 쓰기 불가
#   → alb_access_logs.tf와 동일 이유로 AES256 전용
# =============================================

# ─────────────────────────────────────────────────────
# 로그 보존 기간 변수
# ⚠️ 기본 제안값 90일 — 확정 후 조정
# ─────────────────────────────────────────────────────
variable "s3_access_log_retention_days" {
  description = "S3 Server Access Log 보존 기간(일) — 전자금융거래법 최소 기준"
  type        = number
  default     = 90
}

# ─────────────────────────────────────────────────────
# S3 Access Log 중앙 수집 버킷 (target)
# ─────────────────────────────────────────────────────
resource "aws_s3_bucket" "s3_access_logs" {
  bucket = "financial-s3-access-logs-${var.account_id}"

  tags = {
    Project            = "ilpumjinro"
    ManagedBy          = "terraform"
    Owner              = "security"
    Service            = "S3AccessLogs"
    Environment        = "all"
    DataClassification = "Internal"
  }
}

resource "aws_s3_bucket_public_access_block" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3(AES256) — SSE-KMS는 log delivery 서비스와 비호환
resource "aws_s3_bucket_server_side_encryption_configuration" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

# 로그 만료 정책 — var.s3_access_log_retention_days로 조정 (기본 90일)
resource "aws_s3_bucket_lifecycle_configuration" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  rule {
    id     = "expire-access-logs"
    status = "Enabled"
    filter { prefix = "s3-access/" } # 모든 source prefix 공통 부모

    expiration {
      days = var.s3_access_log_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.s3_access_log_retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.s3_access_logs]
}

# ─────────────────────────────────────────────────────
# Bucket Policy — S3 log delivery 서비스 PutObject 허용
#
# 추가된 IAM 권한:
#   Principal : logging.s3.amazonaws.com (S3 서버 액세스 로그 전달 서비스)
#   Action    : s3:PutObject
#   Resource  : {bucket}/s3-access/* (5개 source prefix 전체 커버)
#   Condition : aws:SourceAccount = account_id (confused deputy 방지)
# ─────────────────────────────────────────────────────
resource "aws_s3_bucket_policy" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  # public access block 먼저 적용 후 policy 부여 (alb_access_logs.tf 동일 패턴)
  depends_on = [aws_s3_bucket_public_access_block.s3_access_logs]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowS3LogDelivery"
      Effect = "Allow"
      Principal = {
        Service = "logging.s3.amazonaws.com"
      }
      Action   = "s3:PutObject"
      Resource = "${aws_s3_bucket.s3_access_logs.arn}/s3-access/*"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = var.account_id
        }
      }
    }]
  })
}

# ─────────────────────────────────────────────────────
# Source 버킷 로깅 설정 — security 모듈 관리 버킷
# bootstrap 관리 버킷 4개는 bootstrap/s3_access_logging.tf에서 정의
# ─────────────────────────────────────────────────────
resource "aws_s3_bucket_logging" "prowler_findings" {
  bucket = aws_s3_bucket.prowler_findings.id

  target_bucket = aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/prowler-findings/"
}
