output "terraform_state_bucket_name" {
  description = "Terraform state 버킷 이름"
  value       = aws_s3_bucket.terraform_state.bucket
}

output "terraform_state_bucket_arn" {
  description = "Terraform state 버킷 ARN"
  value       = aws_s3_bucket.terraform_state.arn
}

output "cloudtrail_logs_locked_bucket_name" {
  description = "CloudTrail 로그 버킷 이름"
  value       = aws_s3_bucket.cloudtrail_logs_locked.bucket
}

output "cloudtrail_logs_locked_bucket_arn" {
  description = "CloudTrail 로그 버킷 ARN"
  value       = aws_s3_bucket.cloudtrail_logs_locked.arn
}