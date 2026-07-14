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
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 서버측 암호화 (AES256)
resource "aws_s3_bucket_server_side_encryption_configuration" "thanos_objstore" {
  bucket = aws_s3_bucket.thanos_objstore.id
  rule {
    apply_server_side_encryption_by_default {
      # 팀 표준: 기존 S3 KMS 키(var.kms_key_s3_arn, 루트의 key_s3) 재사용 (flowlogs 버킷과 동일)
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_s3_arn
    }
    bucket_key_enabled = true
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
          "aws:RequestTag/kubernetes-namespace" = "observability"
          # 실제 Bitnami Thanos 컴포넌트 ServiceAccount와 일치해야 Pod Identity가
          # 이 role을 AssumeRole할 수 있다. 기존 "thanos" 조건은 어느 워크로드에도
          # 매칭되지 않아 Ruler의 S3 object 확인이 Access Denied로 실패했다.
          "aws:RequestTag/kubernetes-service-account" = [
            "observability-thanos-ruler",
            "observability-thanos-receive",
          ]
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
        Sid      = "ListBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
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
      },
      {
        # KMS 암호화 버킷 객체 R/W에 필요 (해당 S3 키로만 제한)
        Sid    = "KmsForObjstore"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = [var.kms_key_s3_arn]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "thanos_objstore" {
  role       = aws_iam_role.thanos_objstore.name
  policy_arn = aws_iam_policy.thanos_objstore.arn
}

resource "aws_eks_pod_identity_association" "thanos_ruler_objstore" {
  cluster_name = aws_eks_cluster.ops.name
  namespace    = "observability"
  # Bitnami thanos 차트는 컴포넌트별 SA를 생성한다 (release: observability-thanos).
  # ruler가 objstore(S3)에 평가 블록을 업로드하므로 ruler SA에 권한 부여.
  service_account = "observability-thanos-ruler"
  role_arn        = aws_iam_role.thanos_objstore.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy_attachment.thanos_objstore,
  ]
}

resource "aws_eks_pod_identity_association" "thanos_receive_objstore" {
  cluster_name = aws_eks_cluster.ops.name
  namespace    = "observability"
  # receive도 objstoreConfig가 설정되면 TSDB 블록을 S3로 업로드하므로 동일 권한 필요.
  service_account = "observability-thanos-receive"
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
