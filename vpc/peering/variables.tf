# ── VPC ID ────────────────────────────────────────────────────────────────────

variable "vpc1_id" {
  description = "VPC 1 ID"
  type        = string
}

variable "vpc2_id" {
  description = "VPC 2 ID"
  type        = string
}

variable "vpc3_id" {
  description = "VPC 3 ID"
  type        = string
}

variable "vpc4_id" {
  description = "VPC 4 ID"
  type        = string
}

# ── VPC CIDR ──────────────────────────────────────────────────────────────────

variable "vpc1_cidr" {
  description = "VPC 1 CIDR"
  type        = string
}

variable "vpc2_cidr" {
  description = "VPC 2 CIDR"
  type        = string
}

variable "vpc3_cidr" {
  description = "VPC 3 CIDR"
  type        = string
}

variable "vpc4_cidr" {
  description = "VPC 4 CIDR"
  type        = string
}

# ── VPC 1 라우팅 테이블 ID ────────────────────────────────────────────────────

variable "vpc1_public_rt_id" {
  description = "VPC1 Public 라우팅 테이블 ID"
  type        = string
}

variable "vpc1_private_rt_id" {
  description = "VPC1 Private 라우팅 테이블 ID"
  type        = string
}

variable "vpc1_db_rt_id" {
  description = "VPC1 DB 라우팅 테이블 ID"
  type        = string
}

# ── VPC 2 라우팅 테이블 ID ────────────────────────────────────────────────────

variable "vpc2_private_rt_id" {
  description = "VPC2 Private 라우팅 테이블 ID"
  type        = string
}

variable "vpc2_db_rt_id" {
  description = "VPC2 DB 라우팅 테이블 ID"
  type        = string
}

# ── VPC 3 라우팅 테이블 ID ────────────────────────────────────────────────────

variable "vpc3_private_rt_id" {
  description = "VPC3 Private 라우팅 테이블 ID"
  type        = string
}

# ── VPC 4 라우팅 테이블 ID ────────────────────────────────────────────────────

variable "vpc4_public_rt_id" {
  description = "VPC4 Public 라우팅 테이블 ID"
  type        = string
}
