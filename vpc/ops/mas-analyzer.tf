resource "aws_iam_role" "mas_analyzer" {
  name = "${var.eks_cluster_name}-mas-analyzer-role"

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
    Name = "${var.eks_cluster_name}-mas-analyzer-role"
  }
}

resource "aws_iam_role_policy" "mas_analyzer" {
  name = "${var.eks_cluster_name}-mas-analyzer-policy"
  role = aws_iam_role.mas_analyzer.id

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
      }
    ]
  })
}

resource "aws_eks_pod_identity_association" "mas_analyzer" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "mas"
  service_account = "mas-analyzer-agent"
  role_arn        = aws_iam_role.mas_analyzer.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy.mas_analyzer,
  ]
}
