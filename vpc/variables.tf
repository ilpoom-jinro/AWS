variable "vpc1_cidr" {
  description = "VPC 1 — 대국민 서비스망"
  type        = string
  default     = "10.10.0.0/16"
}

variable "vpc2_cidr" {
  description = "VPC 2 — 내부 운영망 (완전 격리)"
  type        = string
  default     = "10.20.0.0/16"
}

variable "vpc3_cidr" {
  description = "VPC 3 — Teleport 접근망"
  type        = string
  default     = "10.30.0.0/16"
}

variable "vpc4_cidr" {
  description = "VPC 4 — Headscale Router (WireGuard)"
  type        = string
  default     = "10.40.0.0/16"
}
