variable "aws_region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "vpc_cidr" {
  description = "VPC 1 CIDR"
  type        = string
  default     = "10.10.0.0/16"
}

variable "vpc2_cidr" {
  description = "VPC 2 CIDR - for Security Group rules"
  type        = string
  default     = "10.20.0.0/16"
}

variable "vpc3_cidr" {
  description = "VPC 3 CIDR - for Security Group rules"
  type        = string
  default     = "10.30.0.0/16"
}

variable "vpc4_cidr" {
  description = "VPC 4 CIDR - for Security Group rules"
  type        = string
  default     = "10.40.0.0/16"
}

variable "eks_cluster_name" {
  description = "Service VPC EKS cluster name"
  type        = string
  default     = "financial-service-eks"
}

variable "eks_cluster_version" {
  description = "Service VPC EKS Kubernetes version"
  type        = string
  default     = "1.35"
}

variable "eks_enabled_cluster_log_types" {
  description = "EKS control plane log types"
  type        = list(string)
  default     = []
}

variable "eks_node_instance_types" {
  description = "Instance types for the service EKS managed node group"
  type        = list(string)
  default     = ["m7i-flex.large"]
}

variable "eks_node_capacity_type" {
  description = "Capacity type for the service EKS managed node group"
  type        = string
  default     = "ON_DEMAND"
}

variable "eks_node_disk_size" {
  description = "Disk size in GiB for service EKS nodes"
  type        = number
  default     = 30
}

variable "eks_node_desired_size" {
  description = "Desired number of service EKS nodes"
  type        = number
  # 2→3: service 클러스터 CPU 포화(노드1 95% requests)로 istio 게이트웨이/waypoint
  # istio-proxy가 startup을 못 끝내 CrashLoop → ALB 타겟 없음 → aws.ilpumjinro.store 503.
  # 노드 1대 추가로 istio 데이터플레인 기동 여유 확보.
  default = 3
}

variable "eks_node_min_size" {
  description = "Minimum number of service EKS nodes"
  type        = number
  default     = 2
}

variable "eks_node_max_size" {
  description = "Maximum number of service EKS nodes"
  type        = number
  default     = 3
}

# ── RDS ───────────────────────────────────────────────────────────────────────

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "single_az_mode" {
  description = "개발 단계 비용 절감용 단일 AZ 모드 - true: RDS Multi-AZ 비활성화, EKS 노드 1대로 축소 / 운영 전환 시 false"
  type        = bool
  default     = false
}

variable "rds_multi_az" {
  description = "Multi-AZ 활성화 여부 (비용 약 2배, 운영 환경에서는 true 권장)"
  type        = bool
  default     = true
}

variable "rds_backup_retention" {
  description = "RDS 자동 백업 보관일. Free Plan 계정은 0 필수(retention>0 시 FreeTierRestrictionError). Paid 계정에서만 tfvars로 7 오버라이드."
  type        = number
  default     = 0 # Free Plan 안전 기본값
}

variable "rds_password" {
  description = "RDS 마스터 비밀번호 — 루트 secrets.tf의 random_password.service_rds에서 주입"
  type        = string
  sensitive   = true
}

variable "deletion_protection" {
  description = "RDS 삭제 방지. 빌드=false(destroy 사이클용), go-live=true"
  type        = bool
  default     = false
}

variable "kms_key_rds_arn" {
  description = "RDS 암호화에 사용할 KMS CMK ARN"
  type        = string
}

variable "kms_key_eks_arn" {
  description = "EKS etcd Secrets 암호화 및 EBS 노드 볼륨 암호화에 사용할 KMS CMK ARN"
  type        = string
}

variable "kms_key_secretsmanager_arn" {
  description = "Secrets Manager CMK ARN — rotation Lambda가 CMK 복호화에 사용"
  type        = string
}

variable "account_id" {
  description = "AWS 계정 ID"
  type        = string
}
