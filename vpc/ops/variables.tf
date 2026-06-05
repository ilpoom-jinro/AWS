variable "aws_region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "vpc_cidr" {
  description = "VPC 2 CIDR"
  type        = string
  default     = "10.20.0.0/16"
}

variable "vpc1_cidr" {
  description = "VPC 1 CIDR - for Security Group rules"
  type        = string
  default     = "10.10.0.0/16"
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
  description = "Internal Ops VPC EKS cluster name"
  type        = string
  default     = "financial-ops-eks"
}

variable "eks_cluster_version" {
  description = "Internal Ops VPC EKS Kubernetes version"
  type        = string
  default     = "1.35"
}

variable "eks_enabled_cluster_log_types" {
  description = "EKS control plane log types"
  type        = list(string)
  default     = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
}

variable "eks_node_instance_types" {
  description = "Instance types for the internal ops EKS managed node group"
  type        = list(string)
  default     = ["c7i-flex.large"]
}

variable "eks_node_capacity_type" {
  description = "Capacity type for the internal ops EKS managed node group"
  type        = string
  default     = "ON_DEMAND"
}

variable "eks_node_disk_size" {
  description = "Disk size in GiB for internal ops EKS nodes"
  type        = number
  default     = 30
}

variable "eks_node_desired_size" {
  description = "Desired number of internal ops EKS nodes"
  type        = number
  default     = 2
}

variable "eks_node_min_size" {
  description = "Minimum number of internal ops EKS nodes"
  type        = number
  default     = 2
}

variable "eks_node_max_size" {
  description = "Maximum number of internal ops EKS nodes"
  type        = number
  default     = 3
}

variable "argocd_namespace" {
  description = "Namespace where Argo CD is installed"
  type        = string
  default     = "argocd"
}

variable "eks_monitor_node_instance_types" {
  description = "monitoring node group instance types"
  type        = list(string)
  default     = ["m7i-flex.large"]
}

variable "eks_monitor_node_desired_size" {
  description = "monitoring node group desired size"
  type        = number
  default     = 1
}

variable "eks_monitor_node_min_size" {
  description = "monitoring node group min size"
  type        = number
  default     = 1
}

variable "eks_monitor_node_max_size" {
  description = "monitoring node group max size"
  type        = number
  default     = 2
}

variable "temporal_db_identifier" {
  description = "RDS instance identifier for Temporal persistence"
  type        = string
  default     = "financial-ops-temporal-postgres"
}

variable "temporal_db_name" {
  description = "Initial PostgreSQL database name for Temporal"
  type        = string
  default     = "temporal"
}

variable "temporal_visibility_db_name" {
  description = "PostgreSQL database name for Temporal visibility data"
  type        = string
  default     = "temporal_visibility"
}

variable "temporal_db_username" {
  description = "Temporal PostgreSQL master username"
  type        = string
  default     = "temporal"
}

variable "temporal_db_engine_version" {
  description = "PostgreSQL engine version for Temporal RDS"
  type        = string
  default     = "16.6"
}

variable "temporal_db_instance_class" {
  description = "RDS instance class for Temporal PostgreSQL"
  type        = string
  default     = "db.t4g.medium"
}

variable "temporal_db_allocated_storage" {
  description = "Initial Temporal RDS storage in GiB"
  type        = number
  default     = 50
}

variable "temporal_db_max_allocated_storage" {
  description = "Maximum Temporal RDS storage autoscaling limit in GiB"
  type        = number
  default     = 200
}

variable "temporal_db_multi_az" {
  description = "Whether Temporal RDS should run in Multi-AZ mode"
  type        = bool
  default     = true
}

variable "temporal_db_backup_retention_period" {
  description = "Temporal RDS automated backup retention in days"
  type        = number
  default     = 7
}

variable "temporal_db_backup_window" {
  description = "Temporal RDS preferred backup window"
  type        = string
  default     = "18:00-19:00"
}

variable "temporal_db_maintenance_window" {
  description = "Temporal RDS preferred maintenance window"
  type        = string
  default     = "sun:19:00-sun:20:00"
}

variable "temporal_db_deletion_protection" {
  description = "Protect Temporal RDS from accidental deletion"
  type        = bool
  default     = true
}

variable "temporal_db_skip_final_snapshot" {
  description = "Skip the final snapshot when Temporal RDS is destroyed"
  type        = bool
  default     = false
}

variable "temporal_db_subnet_group_name" {
  description = "DB subnet group name for Temporal RDS"
  type        = string
  default     = "financial-ops-temporal-db-subnets"
}

variable "temporal_db_parameter_group_name" {
  description = "DB parameter group name for Temporal RDS"
  type        = string
  default     = "financial-ops-temporal-postgres16"
}

variable "temporal_db_parameter_group_family" {
  description = "DB parameter group family for Temporal RDS"
  type        = string
  default     = "postgres16"
}

variable "temporal_db_secret_name" {
  description = "Secrets Manager secret name for Temporal RDS connection settings"
  type        = string
  default     = "financial/ops/temporal/postgres"
}
