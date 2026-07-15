# GCP_sub DR workflows can only inspect and invert Route 53 health checks.
# They cannot modify hosted-zone records or any other AWS resource.
resource "aws_iam_role" "gcp_dr_route53_failover" {
  name        = "ilpumjinro-gcp-dr-route53-failover-role"
  description = "Route 53 health-check control role for GCP DR workflows"

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
          "token.actions.githubusercontent.com:sub" = "repo:ilpoom-jinro/GCP_sub:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "gcp_dr_route53_failover" {
  name = "gcp-dr-route53-health-check-control"
  role = aws_iam_role.gcp_dr_route53_failover.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadHealthChecks"
        Effect = "Allow"
        Action = [
          "route53:GetHealthCheck",
          "route53:GetHealthCheckStatus",
          "route53:ListHealthChecks"
        ]
        Resource = "*"
      },
      {
        Sid      = "InvertHealthChecks"
        Effect   = "Allow"
        Action   = ["route53:UpdateHealthCheck"]
        Resource = "arn:aws:route53:::healthcheck/*"
      }
    ]
  })
}

output "gcp_dr_route53_failover_role_arn" {
  description = "GCP_sub Secret AWS_DR_ROUTE53_ROLE_ARN value"
  value       = aws_iam_role.gcp_dr_route53_failover.arn
}
