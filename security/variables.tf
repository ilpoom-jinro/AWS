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
