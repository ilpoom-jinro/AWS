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

variable "prometheus_image_repository_name" {
  description = "ECR repository name for the mirrored Prometheus image"
  type        = string
  default     = "financial/prometheus"
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

variable "prometheus_image_tag" {
  description = "Prometheus image tag used by the Helm release"
  type        = string
  default     = "v3.7.3"
}

variable "istio_image_repository_prefix" {
  description = "ECR repository prefix for mirrored Istio images"
  type        = string
  default     = "financial/istio"
}

variable "istio_image_tag" {
  description = "Istio image tag and Helm chart version"
  type        = string
  default     = "1.30.0"
}

variable "manifest_updater_codebuild_project_name" {
  description = "CodeBuild project name for updating internal GitOps manifests"
  type        = string
  default     = "financial-manifest-updater"
}

variable "manifest_updater_image" {
  description = "Full CodeBuild runtime image URI. If null, the repository name and tag variables are used."
  type        = string
  default     = null
}

variable "manifest_updater_image_repository_name" {
  description = "ECR repository name for the CodeBuild runtime image with git, awscli, kubectl, and python yaml"
  type        = string
  default     = "financial/ansible-codebuild"
}

variable "manifest_updater_image_tag" {
  description = "Runtime image tag for the manifest updater CodeBuild project"
  type        = string
  default     = "latest"
}

variable "ops_eks_cluster_name" {
  description = "Ops EKS cluster name where internal Git runs"
  type        = string
  default     = "financial-ops-eks"
}

variable "internal_git_namespace" {
  description = "Kubernetes namespace for the internal Git service"
  type        = string
  default     = "git"
}

variable "internal_git_service_name" {
  description = "Kubernetes service name for internal Git HTTP"
  type        = string
  default     = "internal-git-http"
}

variable "internal_git_http_port" {
  description = "Kubernetes service port for internal Git HTTP"
  type        = number
  default     = 3000
}

variable "internal_git_org" {
  description = "Internal Git organization that owns the GitOps repository"
  type        = string
  default     = "gitops"
}

variable "internal_git_repo" {
  description = "Internal GitOps repository name"
  type        = string
  default     = "platform"
}

variable "internal_git_admin_username" {
  description = "Internal Git username used by the manifest updater"
  type        = string
  default     = "gitadmin"
}

variable "internal_git_admin_password" {
  description = "Internal Git password used by the manifest updater"
  type        = string
  sensitive   = true
  default     = "ChangeMe1234"
}
