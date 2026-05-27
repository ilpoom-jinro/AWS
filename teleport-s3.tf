# ──────────────────────────────────────────────────────────────────────────────
# Teleport 세션 로그 S3 버킷
# 개발자가 VPC3 → VPC2 접근 시 세션 기록 저장
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "teleport_sessions" {
  bucket = "ilpumjinro-teleport"

  tags = {
    Name      = "ilpumjinro-teleport"
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Purpose   = "teleport-session-logs"
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
      sse_algorithm = "AES256"
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

# Teleport EC2 IAM Role에 S3 접근 권한 추가
resource "aws_iam_role_policy" "teleport_s3" {
  name = "teleport-session-logs-s3"
  role = module.vpc3.teleport_ec2_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.teleport_sessions.arn,
        "${aws_s3_bucket.teleport_sessions.arn}/*"
      ]
    }]
  })
}
