# IAM permissions for the AWS Load Balancer Controller deployed by Argo CD into
# the Service EKS cluster. The Pod Identity association can be created before the
# ServiceAccount exists. Mirrors vpc/ops/load-balancer-controller.tf.
resource "aws_iam_role" "aws_load_balancer_controller" {
  name = "${var.eks_cluster_name}-aws-load-balancer-controller-role"

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
          "aws:RequestTag/kubernetes-namespace"       = "kube-system"
          "aws:RequestTag/kubernetes-service-account" = "aws-load-balancer-controller"
        }
      }
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-aws-load-balancer-controller-role"
  }
}

resource "aws_iam_policy" "aws_load_balancer_controller" {
  name        = "${var.eks_cluster_name}-aws-load-balancer-controller-policy"
  description = "Permissions for the AWS Load Balancer Controller in the Service EKS cluster"
  policy      = file("${path.module}/policies/aws-load-balancer-controller-policy.json")
}

resource "aws_iam_role_policy_attachment" "aws_load_balancer_controller" {
  role       = aws_iam_role.aws_load_balancer_controller.name
  policy_arn = aws_iam_policy.aws_load_balancer_controller.arn
}

resource "aws_eks_pod_identity_association" "aws_load_balancer_controller" {
  cluster_name    = aws_eks_cluster.service.name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.aws_load_balancer_controller.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy_attachment.aws_load_balancer_controller,
  ]
}

output "aws_load_balancer_controller_role_arn" {
  description = "IAM role ARN used by the Service EKS AWS Load Balancer Controller through EKS Pod Identity"
  value       = aws_iam_role.aws_load_balancer_controller.arn
}
