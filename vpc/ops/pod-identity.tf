# ──────────────────────────────────────────────────────────────────────────────
# EKS Pod Identity 연결
# IRSA 대신 Pod Identity Agent(addon) 방식 사용 — 이미 eks.tf에서 addon 설치됨
# ──────────────────────────────────────────────────────────────────────────────

# ── ESO (External Secrets Operator) ──────────────────────────────────────────

resource "aws_iam_role" "eso" {
  name        = "financial-ops-eso-role"
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
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:financial-*"
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
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "external-secrets"
  service_account = "external-secrets"
  role_arn        = aws_iam_role.eso.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}

# ── MAS Orchestrator ──────────────────────────────────────────────────────────

resource "aws_iam_role" "mas_orchestrator" {
  name        = "financial-ops-mas-orchestrator-role"
  description = "FinOps Orchestrator - Bedrock and Secrets Manager"

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

resource "aws_iam_role_policy_attachment" "mas_orchestrator" {
  role       = aws_iam_role.mas_orchestrator.name
  policy_arn = "arn:aws:iam::${var.account_id}:policy/mas-policy"
}

resource "aws_iam_role_policy" "mas_orchestrator_finops_collector" {
  name = "finops-collector-read"
  role = aws_iam_role.mas_orchestrator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchMetricsRead"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
          "cloudwatch:DescribeAlarms",
        ]
        Resource = "*"
      },
      {
        Sid    = "AthenaAndGlueRead"
        Effect = "Allow"
        Action = [
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StartQueryExecution",
          "athena:StopQueryExecution",
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:GetTable",
          "glue:GetTables",
        ]
        Resource = "*"
      },
      {
        Sid    = "AthenaResultsBucketAccess"
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:GetBucketLocation",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:PutObject",
        ]
        Resource = [
          aws_s3_bucket.finops_athena_results.arn,
          "${aws_s3_bucket.finops_athena_results.arn}/*",
        ]
      },
      {
        Sid    = "CurSourceBucketRead"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2CapacityRead"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeInstanceTypeOfferings",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeRegions",
          "ec2:DescribeSpotPriceHistory",
          "ec2:GetSpotPlacementScores",
          "eks:DescribeCluster",
          "eks:DescribeNodegroup",
          "eks:ListNodegroups",
        ]
        Resource = "*"
      },
      {
        Sid    = "ManagedServiceRead"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetHealth",
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticache:DescribeCacheClusters",
          "elasticache:DescribeReplicationGroups",
          "rds:DescribeDBInstances",
          "rds:DescribeDBClusters",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_eks_pod_identity_association" "mas_orchestrator" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "finops-mas"
  service_account = "finops-orchestrator"
  role_arn        = aws_iam_role.mas_orchestrator.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}

# ── MAS Agent ─────────────────────────────────────────────────────────────────

resource "aws_iam_role" "mas_agent" {
  name        = "financial-ops-mas-agent-role"
  description = "FinOps Agent Pods - Bedrock and Secrets Manager"

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

resource "aws_iam_role_policy_attachment" "mas_agent" {
  role       = aws_iam_role.mas_agent.name
  policy_arn = "arn:aws:iam::${var.account_id}:policy/mas-policy"
}

resource "aws_iam_role_policy" "mas_agent_finops_collector" {
  name = "finops-collector-read"
  role = aws_iam_role.mas_agent.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchMetricsRead"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
          "cloudwatch:DescribeAlarms",
        ]
        Resource = "*"
      },
      {
        Sid    = "AthenaAndGlueRead"
        Effect = "Allow"
        Action = [
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StartQueryExecution",
          "athena:StopQueryExecution",
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:GetTable",
          "glue:GetTables",
        ]
        Resource = "*"
      },
      {
        Sid    = "AthenaResultsBucketAccess"
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:GetBucketLocation",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:PutObject",
        ]
        Resource = [
          aws_s3_bucket.finops_athena_results.arn,
          "${aws_s3_bucket.finops_athena_results.arn}/*",
        ]
      },
      {
        Sid    = "CurSourceBucketRead"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2CapacityRead"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeInstanceTypeOfferings",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeRegions",
          "ec2:DescribeSpotPriceHistory",
          "ec2:GetSpotPlacementScores",
          "eks:DescribeCluster",
          "eks:DescribeNodegroup",
          "eks:ListNodegroups",
        ]
        Resource = "*"
      },
      {
        Sid    = "ManagedServiceRead"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetHealth",
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticache:DescribeCacheClusters",
          "elasticache:DescribeReplicationGroups",
          "rds:DescribeDBInstances",
          "rds:DescribeDBClusters",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_eks_pod_identity_association" "mas_agent" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "finops-mas"
  service_account = "finops-agent"
  role_arn        = aws_iam_role.mas_agent.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}

# ── Observability Indexer ─────────────────────────────────────────────────────

resource "aws_iam_role" "observability_indexer" {
  name        = "financial-ops-observability-indexer-role"
  description = "Observability Indexer CronJob - read-only access to Secrets Manager"

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

resource "aws_iam_role_policy" "observability_indexer" {
  name = "secretsmanager-read"
  role = aws_iam_role.observability_indexer.id

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
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:financial-ops-rds-password*"
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

resource "aws_eks_pod_identity_association" "observability_indexer" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "observability"
  service_account = "observability-indexer"
  role_arn        = aws_iam_role.observability_indexer.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}
