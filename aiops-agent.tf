# ──────────────────────────────────────────────────────────────────────────────
# terraform/aiops-agent.tf
# AIOps Bedrock Agent 전용 인프라
# 기존 AWS-main main.tf에서 이 파일을 import하거나 동일 디렉토리에 추가
# ──────────────────────────────────────────────────────────────────────────────

# ── 변수 ────────────────────────────────────────────────────────────────────
variable "slack_bot_token" {
  description = "Slack Bot OAuth Token (xoxb-...)"
  type        = string
  sensitive   = true
}

# ── 1. IRSA IAM Role ─────────────────────────────────────────────────────────
# EKS Ops 클러스터의 OIDC Provider ARN / Issuer는 vpc2 모듈에서 출력 필요
# vpc2 모듈 outputs.tf에 아래 항목 추가 후 참조:
#   output "oidc_provider_arn" { value = aws_iam_openid_connect_provider.ops.arn }
#   output "oidc_issuer"       { value = aws_eks_cluster.ops.identity[0].oidc[0].issuer }

data "aws_iam_policy_document" "aiops_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.vpc2.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(module.vpc2.oidc_issuer, "https://", "")}:sub"
      values   = ["system:serviceaccount:aiops:aiops-agent"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(module.vpc2.oidc_issuer, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "aiops_agent" {
  name               = "financial-aiops-agent-role"
  description        = "AIOps Bedrock Agent IRSA Role — VPC2 Ops EKS 상주"
  assume_role_policy = data.aws_iam_policy_document.aiops_assume.json

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
      # CloudWatch Logs 조회 (EKS 컨트롤 플레인 로그)
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
      # CloudWatch Metrics 조회 (Container Insights)
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
      # EKS 클러스터 정보 조회
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
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:aiops/*"
      },
    ]
  })
}

# ── 2. Bedrock Runtime VPC Interface Endpoint (VPC2) ─────────────────────────
resource "aws_security_group" "bedrock_endpoint" {
  name        = "financial-vpc2-bedrock-endpoint-sg"
  description = "Bedrock Runtime VPC Endpoint SG — VPC2 내부 443만 허용"
  vpc_id      = module.vpc2.vpc_id

  ingress {
    description = "Allow HTTPS from VPC2 (aiops-agent → Bedrock)"
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

# ── 3. EKS Access Entry — aiops-agent가 Ops + Service EKS Admin ──────────────
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
  depends_on    = [aws_eks_access_entry.aiops_ops]
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
  depends_on    = [aws_eks_access_entry.aiops_svc]
}

# ── 4. Secrets Manager — Slack Bot Token ─────────────────────────────────────
resource "aws_secretsmanager_secret" "slack_bot_token" {
  name                    = "aiops/slack-bot-token"
  description             = "AIOps Agent Slack Bot OAuth Token"
  recovery_window_in_days = 7

  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
  }
}

resource "aws_secretsmanager_secret_version" "slack_bot_token" {
  secret_id     = aws_secretsmanager_secret.slack_bot_token.id
  secret_string = jsonencode({ token = var.slack_bot_token })
}

# ── 5. ECR Repository — aiops-agent 이미지 ───────────────────────────────────
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
  description = "AIOps Agent IRSA Role ARN (k8s/serviceaccount.yaml annotation에 사용)"
  value       = aws_iam_role.aiops_agent.arn
}

output "aiops_agent_ecr_url" {
  description = "AIOps Agent ECR Repository URL"
  value       = aws_ecr_repository.aiops_agent.repository_url
}
