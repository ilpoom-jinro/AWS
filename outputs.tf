output "github_actions_role_arn" {
  description = "GitHub Secrets AWS_ROLE_ARN value"
  value       = module.iam.github_actions_role_arn
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
