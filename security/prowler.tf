# =============================================
# Prowler — AWS 보안 스캐너 (Config 대체)
#
# Config Recorder + Config Rules 제거 후 Prowler가 보안 평가 담당.
# ISMS-P(한국) 기준으로 서울 리전 스캔 → OCSF/CSV/HTML 결과를 S3에 저장.
# 트리거: 수동 (aws codebuild start-build --project-name financial-prowler).
#          정기 스캔(EventBridge Scheduler)은 MAS 단계.
# =============================================

# =============================================
# S3 버킷 — Prowler 스캔 결과 저장
#
# config_snapshot 버킷과 동일 암호화 패턴 (aws:kms + key_s3_arn).
# force_destroy = true: 스캔 결과는 재생성 가능 → destroy/apply 편의.
# =============================================
resource "aws_s3_bucket" "prowler_findings" {
  bucket        = "financial-prowler-findings-${var.account_id}"
  force_destroy = true

  tags = {
    Project            = "ilpumjinro"
    ManagedBy          = "terraform"
    Owner              = "security"
    Service            = "Prowler"
    Environment        = "all"
    DataClassification = "Internal"
  }
}

resource "aws_s3_bucket_public_access_block" "prowler_findings" {
  bucket = aws_s3_bucket.prowler_findings.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "prowler_findings" {
  bucket = aws_s3_bucket.prowler_findings.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.key_s3_arn
    }
    bucket_key_enabled = true
  }
}

# =============================================
# IAM Role — Prowler CodeBuild 서비스롤
# ansible_codebuild 롤 패턴 복제
# =============================================
resource "aws_iam_role" "prowler_codebuild" {
  name        = "financial-prowler-codebuild-role"
  description = "Prowler security scanner CodeBuild role"

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
    Service     = "Prowler"
    Environment = "all"
  }
}

resource "aws_iam_role_policy_attachment" "prowler_security_audit" {
  role       = aws_iam_role.prowler_codebuild.name
  policy_arn = "arn:aws:iam::aws:policy/SecurityAudit"
}

resource "aws_iam_role_policy_attachment" "prowler_view_only" {
  role       = aws_iam_role.prowler_codebuild.name
  policy_arn = "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess"
}

resource "aws_iam_role_policy" "prowler_codebuild" {
  name = "financial-prowler-codebuild-policy"
  role = aws_iam_role.prowler_codebuild.id

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
        Sid    = "ProwlerResultsS3"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetBucketLocation",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.prowler_findings.arn,
          "${aws_s3_bucket.prowler_findings.arn}/*"
        ]
      },
      {
        # SSE-KMS 버킷에 PutObject 시 S3가 이 롤 자격으로 KMS를 직접 호출
        Sid    = "ProwlerResultsKMS"
        Effect = "Allow"
        Action = [
          "kms:GenerateDataKey*",
          "kms:Encrypt",
          "kms:DescribeKey"
        ]
        Resource = var.key_s3_arn
      }
    ]
  })
}

# =============================================
# CodeBuild Project — Prowler 스캐너
#
# image: ECR Public 공식 이미지 → image_pull_credentials_type = "CODEBUILD"
#        (Private ECR의 SERVICE_ROLE과 다름)
# vpc_config 없음 — Prowler는 AWS API만 호출, VPC 진입 불필요
# 결과는 buildspec 내 -B 옵션으로 S3에 직접 푸시 → artifacts 불필요
# =============================================
resource "aws_codebuild_project" "prowler" {
  name          = "financial-prowler"
  description   = "Prowler ISMS-P 보안 스캔 — 결과를 S3에 OCSF/CSV/HTML로 저장"
  service_role  = aws_iam_role.prowler_codebuild.arn
  build_timeout = 60

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "public.ecr.aws/prowler-cloud/prowler:latest"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "ACCOUNT_ID"
      value = var.account_id
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("${path.module}/../buildspec-prowler.yml")
  }

  tags = {
    Name        = "financial-prowler"
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "Prowler"
    Environment = "all"
  }

  depends_on = [aws_iam_role_policy.prowler_codebuild]
}
