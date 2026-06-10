# ─────────────────────────────────────
# Terraform State S3 버킷
# ─────────────────────────────────────
resource "aws_s3_bucket" "terraform_state" {
  bucket = "ilpumjinro-terraform-state-v2"
  lifecycle {
    prevent_destroy = true
  }
  tags = {
    Name      = "ilpumjinro-terraform-state-v2"
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
      sse_algorithm = "AES256"
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
  bucket              = "ilpumjinro-cloudtrail-logs-locked-v2"
  object_lock_enabled = true
  lifecycle {
    prevent_destroy = false
  }
  tags = {
    Name      = "ilpumjinro-cloudtrail-logs-locked-v2"
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
      sse_algorithm = "AES256"
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
      mode = "GOVERNANCE"
      days = 90
    }
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
        Resource = "arn:aws:s3:::ilpumjinro-cloudtrail-logs-locked-v2"
      },
      {
        Sid    = "AWSCloudTrailWrite"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action   = "s3:PutObject"
        Resource = "arn:aws:s3:::ilpumjinro-cloudtrail-logs-locked-v2/AWSLogs/281257473551/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl" = "bucket-owner-full-control"
          }
        }
      }
    ]
  })
}