# GCP_sub can assume this role only to copy the two DR application images from ECR.
data "aws_region" "current" {}

resource "aws_iam_role" "gcp_dr_image_mirror" {
  name        = "ilpumjinro-gcp-dr-image-mirror-role"
  description = "Read-only ECR role for the GCP DR image mirror workflow"

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
        StringEquals = {
          "token.actions.githubusercontent.com:sub" = "repo:ilpoom-jinro/GCP_sub:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "gcp_dr_image_mirror" {
  name = "gcp-dr-image-mirror-ecr-read"
  role = aws_iam_role.gcp_dr_image_mirror.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "GetEcrAuthorizationToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ReadDrApplicationImages"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:DescribeImages",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = [
          "arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/financial/demo-app-backend",
          "arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/financial/demo-app-frontend"
        ]
      }
    ]
  })
}

output "gcp_dr_image_mirror_role_arn" {
  description = "GitHub Secret AWS_DR_IMAGE_MIRROR_ROLE_ARN value for GCP_sub"
  value       = aws_iam_role.gcp_dr_image_mirror.arn
}
