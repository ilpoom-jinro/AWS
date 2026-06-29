output "kms_key_rds_ops_arn" {
  description = "RDS CMK ARN for financial-vpc2-ops"
  value       = aws_kms_key.key_rds_ops.arn
}

output "kms_key_rds_globalservice_arn" {
  description = "RDS CMK ARN for financial-vpc1-service"
  value       = aws_kms_key.key_rds_globalservice.arn
}

output "kms_key_cloudtrail_arn" {
  description = "CloudTrail CMK ARN"
  value       = aws_kms_key.key_cloudtrail.arn
}

output "kms_key_s3_arn" {
  description = "S3 CMK ARN"
  value       = aws_kms_key.key_s3.arn
}

output "kms_key_secretsmanager_arn" {
  description = "Secrets Manager CMK ARN"
  value       = aws_kms_key.key_secretsmanager.arn
}

output "kms_key_eks_arn" {
  description = "EKS CMK ARN (etcd Secrets + EBS node volumes)"
  value       = aws_kms_key.key_eks.arn
}

output "kms_key_cosign_arn" {
  description = "Cosign CMK ARN (ECR 이미지 서명용 비대칭 키)"
  value       = aws_kms_key.key_cosign.arn
}

output "kms_key_cosign_alias" {
  description = "Cosign CMK alias name"
  value       = aws_kms_alias.key_cosign.name
}
