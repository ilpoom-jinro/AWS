# IAM permissions for the Observability Indexer that reads managed AWS telemetry
# and writes selected summaries to Aurora PostgreSQL through the private VPC path.
resource "aws_iam_role" "observability_indexer" {
  name = "${var.eks_cluster_name}-observability-indexer-role"

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
          "aws:RequestTag/kubernetes-service-account" = "observability-indexer"
        }
      }
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-observability-indexer-role"
  }
}

resource "aws_iam_role_policy" "observability_indexer" {
  name = "${var.eks_cluster_name}-observability-indexer-read-policy"
  role = aws_iam_role.observability_indexer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowReadingXRayTraces"
        Effect = "Allow"
        Action = [
          "xray:GetTraceSummaries",
          "xray:BatchGetTraces",
          "xray:GetServiceGraph",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_eks_pod_identity_association" "observability_indexer" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "observability"
  service_account = "observability-indexer"
  role_arn        = aws_iam_role.observability_indexer.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy.observability_indexer,
  ]
}

output "observability_indexer_role_arn" {
  description = "IAM role ARN used by the Observability Indexer through EKS Pod Identity"
  value       = aws_iam_role.observability_indexer.arn
}

output "xray_vpc_endpoint_id" {
  description = "Interface VPC endpoint used by the Observability Indexer to read AWS X-Ray"
  value       = aws_vpc_endpoint.xray.id
}
