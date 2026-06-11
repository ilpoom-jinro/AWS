# ──────────────────────────────────────────────────────────────────────────────
# terraform/aiops-agent.tf — AIOps Bedrock Agent 인프라
#
# [v0.2 수정사항]
# - 기존: module.vpc2.oidc_provider_arn / oidc_issuer 참조
#   → 기존 vpc2 모듈에 해당 output이 없어 terraform plan 즉시 실패
# - 수정: EKS Pod Identity 방식으로 전환.
#   기존 인프라가 EBS CSI Driver를 Pod Identity로 운영 중이고
#   eks-pod-identity-agent 애드온이 이미 설치되어 있으므로
#   OIDC Provider 없이 동작한다. ServiceAccount annotation도 불필요.
#
# 필요 모듈 output (기존에 이미 존재):
#   module.vpc1.eks_cluster_name, module.vpc2.eks_cluster_name
#   module.vpc2.vpc_id, module.vpc2.vpc_cidr, module.vpc2.private_subnet_ids
# ──────────────────────────────────────────────────────────────────────────────

# ── 변수 ────────────────────────────────────────────────────────────────────
variable "slack_bot_token" {
  description = "Slack Bot OAuth Token (xoxb-...)"
  type        = string
  sensitive   = true
}

variable "slack_signing_secret" {
  description = "Slack App Signing Secret (WebHook 서명 검증용)"
  type        = string
  sensitive   = true
  default     = ""
}

data "aws_caller_identity" "aiops" {}

# ── 1. IAM Role — EKS Pod Identity 신뢰 정책 ─────────────────────────────────
resource "aws_iam_role" "aiops_agent" {
  name        = "financial-aiops-agent-role"
  description = "AIOps Bedrock Agent Pod Identity Role — VPC2 Ops EKS 상주"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
      Action = [
        "sts:AssumeRole",
        "sts:TagSession",
      ]
    }]
  })

  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "platform"
  }
}

resource "aws_iam_role_policy" "aiops_agent" {
  name = "financial-aiops-agent-policy"
  role = aws_iam_role.aiops_agent.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Bedrock 모델 호출 (Claude 3.5 Sonnet)
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
        ]
      },
      # CloudWatch Logs 조회
      {
        Sid    = "CWLogsRead"
        Effect = "Allow"
        Action = [
          "logs:FilterLogEvents",
          "logs:GetLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
        ]
        Resource = "*"
      },
      # CloudWatch Metrics 조회
      {
        Sid    = "CWMetricsRead"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
        ]
        Resource = "*"
      },
      # EKS 클러스터 정보 조회 + 토큰 발급 (aws eks get-token / update-kubeconfig)
      {
        Sid    = "EKSRead"
        Effect = "Allow"
        Action = ["eks:DescribeCluster", "eks:ListClusters"]
        Resource = "*"
      },
      # Secrets Manager — Slack 토큰 조회
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.aiops.account_id}:secret:aiops/*"
      },
    ]
  })
}

# ── 2. EKS Pod Identity Association ──────────────────────────────────────────
# eks-pod-identity-agent 애드온이 Ops EKS에 이미 설치되어 있어야 함
# (기존 eks.tf에서 EBS CSI용으로 이미 설치됨)
resource "aws_eks_pod_identity_association" "aiops" {
  cluster_name    = module.vpc2.eks_cluster_name
  namespace       = "aiops"
  service_account = "aiops-agent"
  role_arn        = aws_iam_role.aiops_agent.arn

  tags = { Name = "aiops-agent-pod-identity" }
}

# ── 3. Bedrock Runtime VPC Interface Endpoint (VPC2) ─────────────────────────
resource "aws_security_group" "bedrock_endpoint" {
  name        = "financial-vpc2-bedrock-endpoint-sg"
  description = "Bedrock Runtime VPC Endpoint SG — VPC2 내부 443만 허용"
  vpc_id      = module.vpc2.vpc_id

  ingress {
    description = "Allow HTTPS from VPC2 (aiops-agent to Bedrock)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [module.vpc2.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "financial-vpc2-bedrock-endpoint-sg" }
}

resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = module.vpc2.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = module.vpc2.private_subnet_ids
  security_group_ids  = [aws_security_group.bedrock_endpoint.id]
  private_dns_enabled = true

  tags = { Name = "financial-vpc2-endpoint-bedrock-runtime" }
}

# ── 4. EKS Access Entry — Role이 두 클러스터 모두 Admin 접근 ──────────────────
resource "aws_eks_access_entry" "aiops_ops" {
  cluster_name  = module.vpc2.eks_cluster_name
  principal_arn = aws_iam_role.aiops_agent.arn
  type          = "STANDARD"
  tags          = { Name = "aiops-agent-ops-access" }
}

resource "aws_eks_access_policy_association" "aiops_ops" {
  cluster_name  = module.vpc2.eks_cluster_name
  principal_arn = aws_iam_role.aiops_agent.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
  depends_on = [aws_eks_access_entry.aiops_ops]
}

resource "aws_eks_access_entry" "aiops_svc" {
  cluster_name  = module.vpc1.eks_cluster_name
  principal_arn = aws_iam_role.aiops_agent.arn
  type          = "STANDARD"
  tags          = { Name = "aiops-agent-service-access" }
}

resource "aws_eks_access_policy_association" "aiops_svc" {
  cluster_name  = module.vpc1.eks_cluster_name
  principal_arn = aws_iam_role.aiops_agent.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
  depends_on = [aws_eks_access_entry.aiops_svc]
}

# ── 5. Secrets Manager — Slack 자격증명 ──────────────────────────────────────
resource "aws_secretsmanager_secret" "slack_bot_token" {
  name                    = "aiops/slack-bot-token"
  description             = "AIOps Agent Slack Bot Token + Signing Secret"
  recovery_window_in_days = 7

  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
  }
}

resource "aws_secretsmanager_secret_version" "slack_bot_token" {
  secret_id = aws_secretsmanager_secret.slack_bot_token.id
  secret_string = jsonencode({
    token          = var.slack_bot_token
    signing_secret = var.slack_signing_secret
  })
}

# ── 6. ECR Repository ─────────────────────────────────────────────────────────
resource "aws_ecr_repository" "aiops_agent" {
  name                 = "financial/aiops-agent"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/aiops-agent"
    Purpose   = "aiops-agent-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "aiops_agent" {
  repository = aws_ecr_repository.aiops_agent.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "최신 이미지 10개 유지"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "aiops_agent_role_arn" {
  description = "AIOps Agent Pod Identity Role ARN"
  value       = aws_iam_role.aiops_agent.arn
}

output "aiops_agent_ecr_url" {
  description = "AIOps Agent ECR Repository URL"
  value       = aws_ecr_repository.aiops_agent.repository_url
}

output "aiops_ops_cluster_name" {
  description = "ConfigMap OPS_EKS_CLUSTER_NAME에 설정할 값"
  value       = module.vpc2.eks_cluster_name
}

output "aiops_service_cluster_name" {
  description = "ConfigMap SERVICE_EKS_CLUSTER_NAME에 설정할 값"
  value       = module.vpc1.eks_cluster_name
}
