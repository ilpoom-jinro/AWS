variable "gcp_fixed_ip" {
  description = "GCP Tailscale node fixed external IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}

variable "gcp_service_ip" {
  description = "GCP 서비스 LB 정적 IP — Route53 Failover SECONDARY 및 gcp.ilpumjinro.store 대상 (plain IP, e.g. 1.2.3.4). GCP LB 배포 후 입력"
  type        = string
  default     = ""
}

variable "aiops_alb_dns_name" {
  description = "financial-ops-eks AIOps Ingress ALB DNS name — AIOps 배포 후 kubectl get ingress -n aiops 로 확인"
  type        = string
  default     = ""
}

variable "oci_headscale_ip" {
  description = "OCI Headscale server IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}

variable "oci_headscale_ip_plain" {
  description = "OCI Headscale server IP (plain format, e.g. 1.2.3.4)"
  type        = string
}

variable "headscale_login_server" {
  description = "Headscale control-plane URL used by Tailscale clients"
  type        = string
  default     = "https://headscale.ilpumjinro.cloud"
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

variable "rds_backup_retention" {
  description = "RDS 자동 백업 보관일. Free Plan 계정은 0 필수(retention>0 시 FreeTierRestrictionError). Paid 계정에서만 tfvars로 7 오버라이드."
  type        = number
  default     = 0 # Free Plan 안전 기본값
}

variable "teleport_image_repository_name" {
  description = "ECR repository name for Teleport image"
  type        = string
  default     = "financial/teleport"
}

variable "enable_flowlog_s3_archive" {
  description = "VPC Flow Logs ALL 트래픽을 S3(Parquet)에 적재 — vpc1·vpc2 용량·비용 측정용. 측정 완료 후 false로 복원. (선행조건: kms/ apply 후 루트 apply)"
  type        = bool
  default     = false
}

variable "enable_pii_scan" {
  description = "PII 스캔 파이프라인 활성화 플래그 — 더미 데이터 검증 완료 후 MAS 단계에서 true. false일 때 S3/CodeBuild/IAM만 내려가고 ECR 이미지는 유지."
  type        = bool
  default     = false
}

variable "pii_scan_target_buckets" {
  description = "PII 스캔 추가 대상 버킷 이름 목록 (testdata 버킷은 코드가 자동 포함하므로 기본값 빈 배열 가능)"
  type        = list(string)
  default     = []
}
