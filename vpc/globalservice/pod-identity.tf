# ──────────────────────────────────────────────────────────────────────────────
# EKS Pod Identity 연결 — financial-service-eks
# IRSA 대신 Pod Identity Agent(addon) 방식 사용 — eks.tf에서 addon 설치됨
# ──────────────────────────────────────────────────────────────────────────────

# ── ESO (External Secrets Operator) ──────────────────────────────────────────

resource "aws_iam_role" "eso" {
  name        = "financial-service-eso-role"
  description = "External Secrets Operator - read-only access to Secrets Manager"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowEKSPodIdentity"
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
      Action = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })

  tags = {
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role_policy" "eso" {
  name = "secretsmanager-read"
  role = aws_iam_role.eso.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:financial-service-rds-password*"
      },
      {
        Sid      = "KMSDecrypt"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:DescribeKey"]
        Resource = var.kms_key_secretsmanager_arn
      }
    ]
  })
}

resource "aws_eks_pod_identity_association" "eso" {
  cluster_name    = aws_eks_cluster.service.name
  namespace       = "external-secrets"
  service_account = "external-secrets"
  role_arn        = aws_iam_role.eso.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}

# ── Kyverno ───────────────────────────────────────────────────────────────────

resource "aws_iam_role" "kyverno" {
  name        = "financial-service-kyverno-role"
  description = "Kyverno image verification - ECR read for signature verification"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowEKSPodIdentity"
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
      Action = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })

  tags = {
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role_policy" "kyverno" {
  name = "ecr-read"
  role = aws_iam_role.kyverno.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRTokenAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRImageRead"
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
          "ecr:DescribeImages",
          "ecr:DescribeRepositories",
        ]
        Resource = "arn:aws:ecr:${var.aws_region}:${var.account_id}:repository/*"
      },
    ]
  })
}

resource "aws_eks_pod_identity_association" "kyverno_admission" {
  cluster_name    = aws_eks_cluster.service.name
  namespace       = "kyverno"
  service_account = "kyverno-admission-controller"
  role_arn        = aws_iam_role.kyverno.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}

resource "aws_eks_pod_identity_association" "kyverno_background" {
  cluster_name    = aws_eks_cluster.service.name
  namespace       = "kyverno"
  service_account = "kyverno-background-controller"
  role_arn        = aws_iam_role.kyverno.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}

resource "aws_eks_pod_identity_association" "kyverno_reports" {
  cluster_name    = aws_eks_cluster.service.name
  namespace       = "kyverno"
  service_account = "kyverno-reports-controller"
  role_arn        = aws_iam_role.kyverno.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}

resource "aws_iam_role" "trivy" {
  name = "financial-service-trivy-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
}

resource "aws_iam_role_policy" "trivy" {
  name = "financial-service-trivy-ecr-read"
  role = aws_iam_role.trivy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRTokenAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRImageRead"
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
          "ecr:DescribeImages",
          "ecr:DescribeRepositories",
        ]
        Resource = "arn:aws:ecr:${var.aws_region}:${var.account_id}:repository/financial/*"
      },
    ]
  })
}

resource "aws_eks_pod_identity_association" "trivy_operator" {
  cluster_name    = aws_eks_cluster.service.name
  namespace       = "trivy"
  service_account = "trivy-operator"
  role_arn        = aws_iam_role.trivy.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}
