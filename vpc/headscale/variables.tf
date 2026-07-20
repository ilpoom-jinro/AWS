variable "aws_region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "vpc_cidr" {
  description = "VPC 4 CIDR"
  type        = string
  default     = "10.40.0.0/16"
}

variable "vpc1_cidr" {
  description = "VPC 1 CIDR - for Security Group rules"
  type        = string
  default     = "10.10.0.0/16"
}

variable "vpc2_cidr" {
  description = "VPC 2 CIDR - for Security Group rules"
  type        = string
  default     = "10.20.0.0/16"
}

variable "gcp_fixed_ip" {
  description = "GCP Tailscale node fixed external IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}

variable "gcp_cloudsql_private_ip" {
  description = "GCP Cloud SQL DR 인스턴스의 사설 IP. 비어 있으면 failback TCP proxy를 생성하지 않음"
  type        = string
  default     = ""
}

variable "service_rds_secret_arn" {
  description = "financial-service RDS 관리자 자격증명이 저장된 Secrets Manager ARN"
  type        = string
}

variable "cloudsql_failback_credentials_secret_arn" {
  description = "GCP Cloud SQL failback 자격증명이 저장된 Secrets Manager ARN (루트 secrets.tf 관리)"
  type        = string
}

variable "service_rds_kms_key_arn" {
  description = "Service RDS Secrets Manager 시크릿을 복호화하는 KMS 키 ARN"
  type        = string
}

variable "gcp_cloudsql_psa_cidr" {
  description = "GCP Cloud SQL Private Services Access CIDR"
  type        = string
  default     = "10.177.232.0/24"
}

variable "cloudsql_failback_proxy_port" {
  description = "AWS Router에서 Cloud SQL로 전달하는 failback 전용 TCP proxy 포트"
  type        = number
  default     = 15432
}

variable "oci_headscale_ip" {
  description = "OCI Headscale server IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}

variable "oci_headscale_ip_plain" {
  description = "OCI Headscale server IP (plain format, e.g. 1.2.3.4) — tailscale up --login-server 용"
  type        = string
}

variable "headscale_login_server" {
  description = "Headscale control-plane URL used by Tailscale clients"
  type        = string
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key for OCI Headscale registration"
  type        = string
  sensitive   = true
}
