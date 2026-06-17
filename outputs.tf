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

output "gitops_bootstrap_codebuild_project_name" {
  description = "CodeBuild project that bootstraps internal GitOps repositories and Argo CD Applications"
  value       = aws_codebuild_project.gitops_bootstrap.name
}

output "cluster_status_codebuild_project_name" {
  description = "CodeBuild project that prints Ops EKS and Argo CD workload status"
  value       = aws_codebuild_project.cluster_status.name
}

output "debug_codebuild_project_name" {
  description = "CodeBuild project that runs debug commands from inside the Ops VPC"
  value       = aws_codebuild_project.debug.name
}

output "mas_status_codebuild_project_name" {
  description = "CodeBuild project that prints MAS UI and Teleport app-service status"
  value       = aws_codebuild_project.mas_status.name
}

output "service_cluster_status_codebuild_project_name" {
  description = "CodeBuild project that prints Service EKS workload status"
  value       = aws_codebuild_project.service_cluster_status.name
}

output "ansible_codebuild_image_repository_url" {
  description = "ECR repository URL for the Ansible CodeBuild runtime image"
  value       = aws_ecr_repository.ansible_codebuild.repository_url
}

output "internal_git_image_repository_url" {
  description = "ECR repository URL for the internal Git runtime image"
  value       = aws_ecr_repository.internal_git.repository_url
}

output "istio_image_repository_prefix" {
  description = "ECR repository prefix used as the Istio image hub"
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.istio_image_repository_prefix}"
}

output "aws_load_balancer_controller_image_repository_url" {
  description = "ECR repository URL for the mirrored AWS Load Balancer Controller image"
  value       = aws_ecr_repository.aws_load_balancer_controller.repository_url
}

output "observability_indexer_image_repository_url" {
  description = "ECR repository URL for the custom Observability Indexer image"
  value       = aws_ecr_repository.observability_indexer.repository_url
}

# =============================================
# Output: rds.tf 작성 시 참조
# 사용법:
#   kms_key_id = data.terraform_remote_state.root.outputs.kms_key_rds_ops_arn
# =============================================

output "kms_key_rds_ops_arn" {
  description = "RDS CMK ARN for financial-vpc2-ops (준호씨 rds.tf에서 참조)"
  value       = aws_kms_key.key_rds_ops.arn
}

output "kms_key_rds_globalservice_arn" {
  description = "RDS CMK ARN for financial-vpc1-service (준호씨 rds.tf에서 참조)"
  value       = aws_kms_key.key_rds_globalservice.arn
}

output "route53_name_servers" {
  description = "가비아 네임서버 설정에 입력할 NS 레코드 4개"
  value       = aws_route53_zone.main.name_servers
}

output "route53_zone_id" {
  description = "ilpumjinro.store Hosted Zone ID"
  value       = aws_route53_zone.main.zone_id
}

output "acm_certificate_arn" {
  description = "ilpumjinro.store ACM 인증서 ARN — ingress.yaml certificate-arn에 입력"
  value       = aws_acm_certificate.main.arn
}
