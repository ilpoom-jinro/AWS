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

variable "temporal_server_image_repository_name" {
  description = "ECR repository name for the mirrored Temporal server image"
  type        = string
  default     = "financial/temporal-server"
}

variable "temporal_admin_tools_image_repository_name" {
  description = "ECR repository name for the mirrored Temporal admin tools image"
  type        = string
  default     = "financial/temporal-admin-tools"
}

variable "temporal_ui_image_repository_name" {
  description = "ECR repository name for the mirrored Temporal UI image"
  type        = string
  default     = "financial/temporal-ui"
}

variable "app_frontend_image_repository_name" {
  description = "Existing ECR repository name for the frontend application image"
  type        = string
  default     = "financial/demo-app-frontend"
}

variable "app_backend_image_repository_name" {
  description = "Existing ECR repository name for the backend application image"
  type        = string
  default     = "financial/demo-app-backend"
}

variable "mas_base_image_repository_name" {
  description = "ECR repository name for the MAS base image"
  type        = string
  default     = "financial/mas-base"
}

variable "mas_orchestrator_image_repository_name" {
  description = "ECR repository name for the MAS orchestrator agent image"
  type        = string
  default     = "financial/mas-orchestrator"
}

variable "mas_observer_image_repository_name" {
  description = "ECR repository name for the MAS observer agent image"
  type        = string
  default     = "financial/mas-observer"
}

variable "mas_analyzer_image_repository_name" {
  description = "ECR repository name for the MAS analyzer agent image"
  type        = string
  default     = "financial/mas-analyzer"
}

variable "mas_ui_image_repository_name" {
  description = "ECR repository name for the MAS UI image"
  type        = string
  default     = "financial/mas-ui"
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

variable "temporal_chart_version" {
  description = "Temporal Helm chart version copied into the internal GitOps repository"
  type        = string
  default     = ""
}

variable "temporal_server_image_tag" {
  description = "Temporal server image tag used by the Helm release"
  type        = string
  default     = "1.31.0"
}

variable "temporal_admin_tools_image_tag" {
  description = "Temporal admin tools image tag used by the Helm release"
  type        = string
  default     = "1.31.0"
}

variable "temporal_ui_image_tag" {
  description = "Temporal UI image tag used by the Helm release"
  type        = string
  default     = "2.49.1"
}

variable "app_frontend_image_tag" {
  description = "Frontend application image tag used by the initial GitOps deployment"
  type        = string
  default     = "latest"
}

variable "app_backend_image_tag" {
  description = "Backend application image tag used by the initial GitOps deployment"
  type        = string
  default     = "latest"
}

variable "mas_agent_image_tag" {
  description = "MAS agent image tag used by Kubernetes deployments"
  type        = string
  default     = "latest"
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

variable "mas_gitops_sync_codebuild_project_name" {
  description = "CodeBuild project name for syncing MAS manifests into the internal GitOps repository"
  type        = string
  default     = "financial-mas-gitops-sync"
}

variable "mas_analyze_codebuild_project_name" {
  description = "CodeBuild project name for invoking the MAS orchestrator analyze API"
  type        = string
  default     = "financial-mas-analyze"
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

variable "dev_mode" {
  description = "개발 기간 임시 전체 권한 플래그"
  type        = bool
  default     = false
}

variable "teleport_image_repository_name" {
  description = "ECR repository name for Teleport image"
  type        = string
  default     = "financial/teleport"
}

variable "teleport_allowed_client_cidrs" {
  description = "Client CIDR blocks allowed to reach the Teleport proxy directly when a network path exists"
  type        = list(string)
  default     = []
}
