resource "aws_iam_role" "github_actions_dev" {
  name        = "ilpumjinro-github-actions-dev-role"
  description = "Dev IAM Role for GitHub Actions Terraform execution via OIDC"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:ilpoom-jinro/AWS:*"
        }
      }
    }]
  })

  tags = {
    Name        = "ilpumjinro-github-actions-dev-role"
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}

# dev role은 AdministratorAccess 사용 (인라인 정책 10240자 제한 초과 문제 해결)
# prod role(github_actions_terraform)은 최소 권한 인라인 정책 유지
resource "aws_iam_role_policy_attachment" "github_actions_dev_admin" {
  role       = aws_iam_role.github_actions_dev.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

output "github_actions_dev_role_arn" {
  description = "GitHub Secrets AWS_ROLE_ARN_DEV value"
  value       = aws_iam_role.github_actions_dev.arn
}
