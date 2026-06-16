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

variable "demo_backend_image_repository_name" {
  description = "ECR repository name for the demo-app backend image"
  type        = string
  default     = "financial/demo-app-backend"
}

variable "demo_backend_image_tag" {
  description = "Initial demo-app backend image tag used by the GitOps bootstrap manifest"
  type        = string
  default     = "latest"
}

variable "demo_frontend_image_repository_name" {
  description = "ECR repository name for the demo-app frontend image"
  type        = string
  default     = "financial/demo-app-frontend"
}

variable "demo_frontend_image_tag" {
  description = "Initial demo-app frontend image tag used by the GitOps bootstrap manifest"
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

variable "gitops_bootstrap_codebuild_project_name" {
  description = "CodeBuild project name for bootstrapping internal GitOps repositories and Argo CD Applications"
  type        = string
  default     = "financial-gitops-bootstrap"
}

variable "cluster_status_codebuild_project_name" {
  description = "CodeBuild project name for checking Ops and Service EKS workload status"
  type        = string
  default     = "financial-cluster-status"
}

variable "debug_codebuild_project_name" {
  description = "CodeBuild project name for running debug commands from inside the Ops VPC"
  type        = string
  default     = "financial-debug"
}

variable "ops_vpc_command" {
  description = "Temporary shell command executed by the Gitea auth debug CodeBuild project"
  type        = string
  default     = "kubectl --context $${OPS_CONTEXT} -n git get deploy,svc,pods -o wide"
}

variable "mas_status_codebuild_project_name" {
  description = "CodeBuild project name for checking MAS and Teleport app-service status"
  type        = string
  default     = "financial-mas-status"
}

variable "service_cluster_status_codebuild_project_name" {
  description = "CodeBuild project name for checking Service EKS workload status from inside the Service VPC"
  type        = string
  default     = "financial-service-cluster-status"
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
  description = "Internal Git organization/user that owns the GitOps repository"
  type        = string
  default     = "gitadmin"
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

variable "dev_mode" {
  description = "개발 기간 임시 전체 권한 플래그"
  type        = bool
  default     = false
}

variable "single_az_mode" {
  description = "개발 단계 비용 절감용 단일 AZ 모드 - true: RDS Multi-AZ 비활성화, EKS 노드 1대로 축소, VPC Endpoint를 단일 AZ로 구성 / 운영 전환 시 false로 변경하여 멀티 AZ 구성 복원"
  type        = bool
  default     = true
}

variable "teleport_image_repository_name" {
  description = "ECR repository name for Teleport image"
  type        = string
  default     = "financial/teleport"
}
