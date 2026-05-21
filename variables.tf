variable "gcp_fixed_ip" {
  description = "GCP Tailscale node fixed external IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}

variable "oci_headscale_ip" {
  description = "OCI Headscale server IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}

variable "oci_headscale_ip_plain" {
  description = "OCI Headscale server IP (plain format, e.g. 1.2.3.4)"
  type        = string
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key for OCI Headscale registration"
  type        = string
  sensitive   = true
}

variable "gitops_codecommit_repository_name" {
  description = "CodeCommit repository name for the GitOps source of truth"
  type        = string
  default     = "gitops-platform"
}

variable "ansible_codebuild_image" {
  description = "CodeBuild image that includes ansible, kubectl, helm, awscli, and python kubernetes dependencies"
  type        = string
  default     = null
}

variable "ansible_codebuild_image_repository_name" {
  description = "ECR repository name for the Ansible CodeBuild runtime image"
  type        = string
  default     = "financial/ansible-codebuild"
}

variable "internal_git_image_repository_name" {
  description = "ECR repository name for the internal Git runtime image"
  type        = string
  default     = "financial/internal-git"
}

variable "argocd_image_repository_name" {
  description = "ECR repository name for the mirrored Argo CD image"
  type        = string
  default     = "financial/argocd"
}

variable "argocd_redis_image_repository_name" {
  description = "ECR repository name for the mirrored Argo CD Redis image"
  type        = string
  default     = "financial/argocd-redis"
}

variable "argocd_image_tag" {
  description = "Argo CD image tag used by the Helm release"
  type        = string
  default     = "latest"
}

variable "argocd_redis_image_tag" {
  description = "Argo CD Redis image tag used by the Helm release"
  type        = string
  default     = "latest"
}

variable "internal_git_admin_username" {
  description = "Initial admin username for the internal Git service"
  type        = string
  default     = "gitadmin"
}

variable "internal_git_admin_password" {
  description = "Initial admin password for the internal Git service"
  type        = string
  sensitive   = true
  default     = "ChangeMe1234"
}
