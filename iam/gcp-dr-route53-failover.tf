# GCP_sub DR workflows can only control the dedicated DR operations below:
# Route 53 health checks and the private-VPC CodeBuild write-fence project.
# They cannot modify hosted-zone records or arbitrary AWS resources.
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
          # Jobs that declare the production Environment receive the environment
          # subject, while non-environment jobs use the branch subject.
          "token.actions.githubusercontent.com:sub" = [
            "repo:ilpoom-jinro/GCP_sub:ref:refs/heads/main",
            "repo:ilpoom-jinro/GCP_sub:environment:production",
          ]
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
      },
      {
        Sid    = "RunServiceWriteFence"
        Effect = "Allow"
        Action = [
          "codebuild:StartBuild",
          "codebuild:BatchGetBuilds"
        ]
        Resource = "arn:aws:codebuild:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:project/financial-service-dr-write-fence"
      }
    ]
  })
}

output "gcp_dr_route53_failover_role_arn" {
  description = "GCP_sub Secret AWS_DR_ROUTE53_ROLE_ARN value"
  value       = aws_iam_role.gcp_dr_route53_failover.arn
}

output "gcp_dr_route53_failover_role_name" {
  description = "DR control role name for root-level least-privilege policies"
  value       = aws_iam_role.gcp_dr_route53_failover.name
}
