output "github_actions_role_arn" {
  description = "GitHub Secrets > AWS_ROLE_ARN 에 등록할 값"
  value       = module.iam.github_actions_role_arn
}
