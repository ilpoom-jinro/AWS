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
  default     = ["t3.small"]
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
  default     = 1
}

variable "eks_node_min_size" {
  description = "Minimum number of internal ops EKS nodes"
  type        = number
  default     = 1
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

