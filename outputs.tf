output "github_actions_role_arn" {
  description = "GitHub Secrets AWS_ROLE_ARN value"
  value       = module.iam.github_actions_role_arn
}

output "github_actions_dev_role_arn" {
  description = "GitHub Secrets AWS_ROLE_ARN_DEV value"
  value       = module.iam.github_actions_dev_role_arn
}

output "service_eks_cluster_name" {
  description = "Service VPC EKS cluster name"
  value       = module.vpc1.eks_cluster_name
}

output "service_eks_cluster_endpoint" {
  description = "Service VPC EKS private API endpoint"
  value       = module.vpc1.eks_cluster_endpoint
}

output "service_eks_cluster_security_group_id" {
  description = "Service VPC EKS cluster security group ID"
  value       = module.vpc1.eks_cluster_security_group_id
}

output "ops_eks_cluster_name" {
  description = "Internal Ops VPC EKS cluster name"
  value       = module.vpc2.eks_cluster_name
}

output "ops_eks_cluster_endpoint" {
  description = "Internal Ops VPC EKS private API endpoint"
  value       = module.vpc2.eks_cluster_endpoint
}

output "ops_eks_cluster_security_group_id" {
  description = "Internal Ops VPC EKS cluster security group ID"
  value       = module.vpc2.eks_cluster_security_group_id
}

output "ansible_codebuild_project_name" {
  description = "CodeBuild project that runs Ansible inside the Ops VPC"
  value       = aws_codebuild_project.ansible_bootstrap.name
}

output "cluster_status_codebuild_project_name" {
  description = "CodeBuild project that prints Ops and Service EKS workload status"
  value       = aws_codebuild_project.cluster_status.name
}

output "ansible_codebuild_image_repository_url" {
  description = "ECR repository URL for the Ansible CodeBuild runtime image"
  value       = aws_ecr_repository.ansible_codebuild.repository_url
}

output "internal_git_image_repository_url" {
  description = "ECR repository URL for the internal Git runtime image"
  value       = aws_ecr_repository.internal_git.repository_url
}

output "prometheus_image_repository_url" {
  description = "ECR repository URL for the mirrored Prometheus image"
  value       = aws_ecr_repository.prometheus.repository_url
}

output "istio_image_repository_prefix" {
  description = "ECR repository prefix used as the Istio image hub"
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.istio_image_repository_prefix}"
}
