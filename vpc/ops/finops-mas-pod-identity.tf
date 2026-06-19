# IAM permissions for the FinOps MAS orchestrator collectors.
resource "aws_iam_role" "finops_mas_orchestrator" {
  name = "${var.eks_cluster_name}-finops-mas-orchestrator-role"

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
          "aws:RequestTag/kubernetes-namespace"       = "finops-mas"
          "aws:RequestTag/kubernetes-service-account" = "finops-orchestrator"
        }
      }
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-finops-mas-orchestrator-role"
  }
}

resource "aws_iam_role_policy" "finops_mas_orchestrator" {
  name = "${var.eks_cluster_name}-finops-mas-orchestrator-read-policy"
  role = aws_iam_role.finops_mas_orchestrator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudWatchMetricsRead"
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
        Sid    = "AllowCostExplorerRead"
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",
          "ce:GetDimensionValues",
          "ce:GetTags",
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowCapacityAndSpotRead"
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
        Sid    = "AllowManagedServiceRead"
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

resource "aws_eks_pod_identity_association" "finops_mas_orchestrator" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "finops-mas"
  service_account = "finops-orchestrator"
  role_arn        = aws_iam_role.finops_mas_orchestrator.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy.finops_mas_orchestrator,
  ]
}

output "finops_mas_orchestrator_role_arn" {
  description = "IAM role ARN used by the FinOps MAS orchestrator through EKS Pod Identity"
  value       = aws_iam_role.finops_mas_orchestrator.arn
}
