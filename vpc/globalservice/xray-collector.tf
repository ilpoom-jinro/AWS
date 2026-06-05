# IAM permissions for the ADOT Collector that sends backend traces to AWS X-Ray.
resource "aws_iam_role" "xray_collector" {
  name = "${var.eks_cluster_name}-xray-collector-role"

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
          "aws:RequestTag/kubernetes-namespace"       = "aws-observability"
          "aws:RequestTag/kubernetes-service-account" = "otel-collector"
        }
      }
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-xray-collector-role"
  }
}

resource "aws_iam_role_policy_attachment" "xray_collector" {
  role       = aws_iam_role.xray_collector.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_eks_pod_identity_association" "xray_collector" {
  cluster_name    = aws_eks_cluster.service.name
  namespace       = "aws-observability"
  service_account = "otel-collector"
  role_arn        = aws_iam_role.xray_collector.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy_attachment.xray_collector,
  ]
}

output "xray_collector_role_arn" {
  description = "IAM role ARN used by the ADOT Collector through EKS Pod Identity"
  value       = aws_iam_role.xray_collector.arn
}
