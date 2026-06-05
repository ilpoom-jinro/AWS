# IAM permissions for the Grafana CloudWatch data source.
resource "aws_iam_role" "grafana_cloudwatch" {
  name = "${var.eks_cluster_name}-grafana-cloudwatch-role"

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
          "aws:RequestTag/kubernetes-service-account" = "grafana"
        }
      }
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-grafana-cloudwatch-role"
  }
}

# Based on Grafana's documented metrics and logs read-only CloudWatch policy.
resource "aws_iam_role_policy" "grafana_cloudwatch" {
  name = "${var.eks_cluster_name}-grafana-cloudwatch-read-policy"
  role = aws_iam_role.grafana_cloudwatch.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowReadingMetricsFromCloudWatch"
        Effect = "Allow"
        Action = [
          "cloudwatch:DescribeAlarmsForMetric",
          "cloudwatch:DescribeAlarmHistory",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:ListMetrics",
          "cloudwatch:GetMetricData",
          "cloudwatch:GetInsightRuleReport",
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowReadingLogsFromCloudWatch"
        Effect = "Allow"
        Action = [
          "logs:DescribeLogGroups",
          "logs:GetLogGroupFields",
          "logs:StartQuery",
          "logs:StopQuery",
          "logs:GetQueryResults",
          "logs:GetLogEvents",
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowReadingTagsInstancesRegionsFromEC2"
        Effect = "Allow"
        Action = [
          "ec2:DescribeTags",
          "ec2:DescribeInstances",
          "ec2:DescribeRegions",
        ]
        Resource = "*"
      },
      {
        Sid      = "AllowReadingResourcesForTags"
        Effect   = "Allow"
        Action   = "tag:GetResources"
        Resource = "*"
      },
      {
        Sid      = "AllowReadingResourceMetricsFromPerformanceInsights"
        Effect   = "Allow"
        Action   = "pi:GetResourceMetrics"
        Resource = "*"
      },
    ]
  })
}

resource "aws_eks_pod_identity_association" "grafana_cloudwatch" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "observability"
  service_account = "grafana"
  role_arn        = aws_iam_role.grafana_cloudwatch.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy.grafana_cloudwatch,
  ]
}

output "grafana_cloudwatch_role_arn" {
  description = "IAM role ARN used by Grafana through EKS Pod Identity"
  value       = aws_iam_role.grafana_cloudwatch.arn
}
