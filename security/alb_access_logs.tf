# ─────────────────────────────────────────────────────────────────
# ALB Access Logs용 S3 버킷 (#13)
#
# ★ 암호화 주의: ALB 로그는 SSE-KMS(CMK) 미지원 → AES256만 됨.
#   key-s3 CMK를 붙이면 전송 실패 후 AccessDenied — 이 버킷만 예외.
# ─────────────────────────────────────────────────────────────────

data "aws_region" "current" {}

locals {
  # 리전별 ELB 서비스 계정 ID (고정값, 본인 계정과 무관)
  # 리전 이전 시 https://docs.aws.amazon.com/elasticloadbalancing/latest/application/enable-access-logging.html 참조
  elb_account_ids = {
    "ap-northeast-2" = "600734575887" # Seoul ELB service account
  }
  elb_account_id = local.elb_account_ids[data.aws_region.current.name]
  alb_log_prefix = "alb"
}

resource "aws_s3_bucket" "alb_logs" {
  bucket = "financial-alb-access-logs-${var.account_id}"

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "ALB"
    Environment = "all"
  }
}

resource "aws_s3_bucket_public_access_block" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# AES256 강제 — CMK(aws:kms)로 바꾸면 ALB 로그 전송 실패
resource "aws_s3_bucket_server_side_encryption_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  rule {
    id     = "expire-old-logs"
    status = "Enabled"
    filter { prefix = "alb/" }
    expiration { days = 7 }
  }
}

# Principal = ELB 서비스 계정(600734575887, 고정)
# Resource 경로의 account_id = var.account_id(본인 계정, 797715838244)
resource "aws_s3_bucket_policy" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id

  depends_on = [aws_s3_bucket_public_access_block.alb_logs]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "ELBAccessLogDelivery"
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${local.elb_account_id}:root" }
      Action    = "s3:PutObject"
      Resource  = "${aws_s3_bucket.alb_logs.arn}/${local.alb_log_prefix}/AWSLogs/${var.account_id}/*"
    }]
  })
}
