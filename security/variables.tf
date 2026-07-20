variable "kms_key_cloudtrail_arn" {
  description = "CloudTrail 암호화에 사용할 KMS CMK ARN"
  type        = string
}

variable "account_id" {
  description = "AWS 계정 ID (root에서 전달, module.security의 depends_on으로 인한 apply-time 평가 회피)"
  type        = string
}

variable "key_s3_arn" {
  description = "key-s3 CMK ARN (루트 data-kms.tf에서 전달)"
  type        = string
}

variable "key_sns_arn" {
  description = "key-sns CMK ARN (루트 data-kms.tf에서 전달, #49 security-violation-alert 암호화용)"
  type        = string
}

variable "enable_pii_scan" {
  description = "PII 스캔 파이프라인 활성화 플래그 (루트에서 전달)"
  type        = bool
}

variable "pii_scan_target_buckets" {
  description = "PII 스캔 추가 대상 버킷 이름 목록 (루트에서 전달)"
  type        = list(string)
}

variable "alert_email" {
  description = "탐지 SNS 알림 수신 이메일 (루트에서 전달) — Breakglass/Root/IAM위반/권한상승/네트워크변경/API이상행위 6종 전체에 구독"
  type        = string
}

variable "pii_scan_ecr_image" {
  description = "PII 스캔 CodeBuild 런타임 이미지 URI — 루트 aws_ecr_repository.pii_scan.repository_url:latest"
  type        = string
}

variable "pii_scan_ecr_repo_arn" {
  description = "PII 스캔 ECR repo ARN — CodeBuild IAM role의 ECR pull 권한 범위 지정"
  type        = string
}

variable "aws_region" {
  description = "AWS 배포 리전 — SIEM Athena results 버킷 이름 suffix용 (finops 패턴 준수)"
  type        = string
  default     = "ap-northeast-2"
}
