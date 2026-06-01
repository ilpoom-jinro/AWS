resource "aws_iam_role" "mas_runtime" {
  name = "${var.eks_cluster_name}-mas-runtime-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
      Action = [
        "sts:AssumeRole",
        "sts:TagSession"
      ]
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-mas-runtime-role"
  }
}

resource "aws_iam_role_policy" "mas_runtime" {
  name = "${var.eks_cluster_name}-mas-runtime-policy"
  role = aws_iam_role.mas_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInference"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "*"
      },
      {
        Sid    = "ReadCloudWatchSignals"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:FilterLogEvents",
          "logs:GetLogEvents",
          "logs:GetQueryResults",
          "logs:StartQuery",
          "logs:StopQuery"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_eks_pod_identity_association" "mas_runtime" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "mas"
  service_account = "mas-runtime"
  role_arn        = aws_iam_role.mas_runtime.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy.mas_runtime,
  ]
}
