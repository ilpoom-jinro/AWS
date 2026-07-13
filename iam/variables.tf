# =============================================
# 개발 기간 임시 권한 플래그
# =============================================
# dev_mode = true  → 전체 팀원 AdministratorAccess (terraform apply 가능)
# dev_mode = false → 각 역할별 최소 권한으로 복귀 (기본값)
#
# 사용법:
#   - GitHub Actions: terraform.yml env에 TF_VAR_dev_mode: "true" 추가
#   - 개발 완료 후: TF_VAR_dev_mode 제거 또는 "false"로 변경
# =============================================

variable "dev_mode" {
  description = "개발 기간 임시 전체 권한 플래그. true = 전 팀원 AdminAccess, false = 역할별 최소 권한"
  type        = bool
  default     = false
}

variable "route53_zone_arn" {
  description = "Route 53 hosted zone ARN used by the GCP DR DNS-01 role"
  type        = string
}
