resource "aws_s3_bucket" "finops_athena_results" {
  bucket        = "financial-finops-athena-results-${var.account_id}-${var.aws_region}"
  force_destroy = true

  tags = {
    Name      = "financial-finops-athena-results"
    ManagedBy = "terraform"
  }
}

resource "aws_s3_bucket_public_access_block" "finops_athena_results" {
  bucket = aws_s3_bucket.finops_athena_results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "finops_athena_results" {
  bucket = aws_s3_bucket.finops_athena_results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "finops_athena_results" {
  bucket = aws_s3_bucket.finops_athena_results.id

  rule {
    id     = "expire-query-results"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
  }
}

resource "aws_glue_catalog_database" "finops_cur" {
  name        = "finops_cur"
  description = "AWS Cost and Usage Report catalog for the FinOps MAS"
}

resource "aws_athena_workgroup" "finops_cur" {
  name        = "finops-cur"
  description = "Private Athena workgroup used by the FinOps Cost Agent"
  state       = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.finops_athena_results.bucket}/query-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }

  depends_on = [
    aws_s3_bucket_public_access_block.finops_athena_results,
    aws_s3_bucket_server_side_encryption_configuration.finops_athena_results,
  ]
}
