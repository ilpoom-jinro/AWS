# =============================================================================
# Thanos Ruler objstore (S3) + Pod Identity
# =============================================================================
# Thanos Ruler를 stateful 모드로 켜기 위한 S3 오브젝트 스토리지와 접근 권한.
# Ruler가 평가한 alerting rule 결과/블록을 이 버킷에 저장한다.
# (Bitnami Thanos 차트는 Ruler에 objstore secret 마운트를 요구하므로 필수)
#
# 접근 방식: EKS Pod Identity (ALB Controller와 동일 패턴)
#   observability 네임스페이스의 thanos ServiceAccount에 연결.

resource "aws_s3_bucket" "thanos_objstore" {
  bucket        = "jinro-observability-thanos-${var.account_id}"
  force_destroy = true

  tags = {
    Name    = "jinro-observability-thanos"
    Purpose = "thanos-ruler-objstore"
    Project = "ilpoomjinro"
  }
}

# 버저닝 (Thanos 블록 정합성 및 실수 복구)
resource "aws_s3_bucket_versioning" "thanos_objstore" {
  bucket = aws_s3_bucket.thanos_objstore.id
  versioning_configuration {
    status = "Enabled"
  }
}

# 퍼블릭 액세스 전면 차단 (금융권 요건)
resource "aws_s3_bucket_public_access_block" "thanos_objstore" {
  bucket                  = aws_s3_bucket.thanos_objstore.id
  block_public_acls       = true
  block_public_policy      = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 서버측 암호화 (AES256)
resource "aws_s3_bucket_server_side_encryption_configuration" "thanos_objstore" {
  bucket = aws_s3_bucket.thanos_objstore.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ---- Pod Identity: IAM Role ----
resource "aws_iam_role" "thanos_objstore" {
  name = "${var.eks_cluster_name}-thanos-objstore-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowEksAuthToAssumeRoleForPodIdentity"
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
      Action = [
        "sts:AssumeRole",
        "sts:TagSession"
      ]
      Condition = {
        StringEquals = {
          "aws:RequestTag/kubernetes-namespace"       = "observability"
          "aws:RequestTag/kubernetes-service-account" = "thanos"
        }
      }
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-thanos-objstore-role"
  }
}

# ---- S3 접근 정책 (해당 버킷으로만 제한) ----
resource "aws_iam_policy" "thanos_objstore" {
  name        = "${var.eks_cluster_name}-thanos-objstore-policy"
  description = "Thanos Ruler objstore access (scoped to the observability bucket)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListBucket"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.thanos_objstore.arn]
      },
      {
        Sid    = "ObjectRW"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = ["${aws_s3_bucket.thanos_objstore.arn}/*"]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "thanos_objstore" {
  role       = aws_iam_role.thanos_objstore.name
  policy_arn = aws_iam_policy.thanos_objstore.arn
}

resource "aws_eks_pod_identity_association" "thanos_objstore" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "observability"
  service_account = "thanos"
  role_arn        = aws_iam_role.thanos_objstore.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy_attachment.thanos_objstore,
  ]
}

output "thanos_objstore_bucket" {
  description = "S3 bucket name for Thanos Ruler objstore"
  value       = aws_s3_bucket.thanos_objstore.bucket
}

output "thanos_objstore_role_arn" {
  description = "IAM role ARN used by Thanos through EKS Pod Identity"
  value       = aws_iam_role.thanos_objstore.arn
}
