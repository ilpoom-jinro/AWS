# =============================================
# PII 탐지 파이프라인 (Presidio 기반)
#
# 활성화: enable_pii_scan = true (기본 false — 더미 데이터 검증 후 MAS 단계에서 켬)
# ECR repo는 루트 ecr.tf에서 count 없이 상시 관리.
# 여기서는 S3/IAM/CodeBuild만 count 게이팅.
#
# flowlogs.tf 패턴 그대로:
#   count  = var.enable_pii_scan ? 1 : 0
#   cross-ref: resource_name[0].attribute
#   depends_on: 인덱스 없이 리소스 전체 참조
# =============================================

# =============================================
# S3 — 더미 테스트 데이터 버킷
# prowler_findings 구조 복제 (force_destroy, SSE-KMS)
# =============================================
resource "aws_s3_bucket" "pii_testdata" {
  count         = var.enable_pii_scan ? 1 : 0
  bucket        = "financial-pii-scan-testdata-${var.account_id}"
  force_destroy = true

  tags = {
    Project            = "ilpumjinro"
    ManagedBy          = "terraform"
    Owner              = "security"
    Service            = "PIIScan"
    Environment        = "all"
    DataClassification = "Internal"
  }
}

resource "aws_s3_bucket_public_access_block" "pii_testdata" {
  count  = var.enable_pii_scan ? 1 : 0
  bucket = aws_s3_bucket.pii_testdata[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pii_testdata" {
  count  = var.enable_pii_scan ? 1 : 0
  bucket = aws_s3_bucket.pii_testdata[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.key_s3_arn
    }
    bucket_key_enabled = true
  }
}

# =============================================
# S3 — PII 탐지 결과 버킷
# prowler_findings 구조 복제
# =============================================
resource "aws_s3_bucket" "pii_findings" {
  count         = var.enable_pii_scan ? 1 : 0
  bucket        = "financial-pii-findings-${var.account_id}"
  force_destroy = true

  tags = {
    Project            = "ilpumjinro"
    ManagedBy          = "terraform"
    Owner              = "security"
    Service            = "PIIScan"
    Environment        = "all"
    DataClassification = "Internal"
  }
}

resource "aws_s3_bucket_public_access_block" "pii_findings" {
  count  = var.enable_pii_scan ? 1 : 0
  bucket = aws_s3_bucket.pii_findings[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pii_findings" {
  count  = var.enable_pii_scan ? 1 : 0
  bucket = aws_s3_bucket.pii_findings[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.key_s3_arn
    }
    bucket_key_enabled = true
  }
}

# =============================================
# IAM Role — PII 스캔 CodeBuild 서비스롤
# prowler_codebuild 패턴 기반, ECR pull 권한 추가
# =============================================
resource "aws_iam_role" "pii_scan_codebuild" {
  count       = var.enable_pii_scan ? 1 : 0
  name        = "financial-pii-scan-codebuild-role"
  description = "Presidio PII scanner CodeBuild role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "codebuild.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "PIIScan"
    Environment = "all"
  }
}

resource "aws_iam_role_policy" "pii_scan_codebuild" {
  count = var.enable_pii_scan ? 1 : 0
  name  = "financial-pii-scan-codebuild-policy"
  role  = aws_iam_role.pii_scan_codebuild[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Logs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      },
      {
        # 스캔 대상: testdata 버킷(항상 포함) + 추가 지정 버킷
        Sid    = "S3Read"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = concat(
          [
            aws_s3_bucket.pii_testdata[0].arn,
            "${aws_s3_bucket.pii_testdata[0].arn}/*"
          ],
          flatten([
            for b in var.pii_scan_target_buckets : [
              "arn:aws:s3:::${b}",
              "arn:aws:s3:::${b}/*"
            ]
          ])
        )
      },
      {
        Sid    = "S3Write"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetBucketLocation",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.pii_findings[0].arn,
          "${aws_s3_bucket.pii_findings[0].arn}/*"
        ]
      },
      {
        # SSE-KMS 버킷 read/write 시 KMS 직접 호출
        Sid    = "KMS"
        Effect = "Allow"
        Action = [
          "kms:GenerateDataKey*",
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = var.key_s3_arn
      },
      {
        # Private ECR 이미지 pull — Prowler(public ECR)와 달리 SERVICE_ROLE 방식
        Sid      = "ECRGetAuthToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRPull"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = var.pii_scan_ecr_repo_arn
      }
    ]
  })
}

# =============================================
# CodeBuild Project — PII 스캐너
#
# Prowler와 차이점:
#   image_pull_credentials_type = "SERVICE_ROLE"  (private ECR이라 CODEBUILD 불가)
#   vpc_config 없음 — S3 API 호출만, VPC 진입 불필요
#   buildspec: 이미지에 베이크인된 /app/scan.py 실행
# =============================================
resource "aws_codebuild_project" "pii_scan" {
  count         = var.enable_pii_scan ? 1 : 0
  name          = "financial-pii-scan"
  description   = "Presidio PII 탐지 — 결과를 S3에 raw/OCSF JSON으로 저장"
  service_role  = aws_iam_role.pii_scan_codebuild[0].arn
  build_timeout = 60

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = var.pii_scan_ecr_image
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "SERVICE_ROLE"

    environment_variable {
      name  = "TARGET_BUCKETS"
      value = join(",", concat(var.pii_scan_target_buckets, [aws_s3_bucket.pii_testdata[0].id]))
    }

    environment_variable {
      name  = "FINDINGS_BUCKET"
      value = aws_s3_bucket.pii_findings[0].id
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("${path.module}/../buildspec-pii-scan.yml")
  }

  tags = {
    Name        = "financial-pii-scan"
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "PIIScan"
    Environment = "all"
  }

  depends_on = [aws_iam_role_policy.pii_scan_codebuild]
}
