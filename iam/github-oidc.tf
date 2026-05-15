# iam/github-oidc.tf

# ─────────────────────────────────────
# GitHub OIDC Identity Provider
# ─────────────────────────────────────
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = {
    Name      = "github-actions-oidc"
    ManagedBy = "terraform"
  }
}

# ─────────────────────────────────────
# GitHub Actions가 Assume할 IAM Role
# ─────────────────────────────────────
resource "aws_iam_role" "github_actions" {
  name        = "ilpumjinro-github-actions-role"
  description = "IAM Role for GitHub Actions Terraform execution via OIDC"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
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
    Name      = "ilpumjinro-github-actions-role"
    ManagedBy = "terraform"
  }
}

# ─────────────────────────────────────
# Terraform 실행 권한 정책
# ─────────────────────────────────────
resource "aws_iam_role_policy" "github_actions_terraform" {
  name = "ilpumjinro-terraform-execution-policy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # tfstate 파일 + .tflock 잠금 파일 접근
        # use_lockfile = true 사용 시 DeleteObject 필수 (잠금 해제)
        Sid    = "TerraformStateAccess"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = [
          "arn:aws:s3:::ilpumjinro-terraform-state",
          "arn:aws:s3:::ilpumjinro-terraform-state/*"
        ]
      },
      {
        # IAM 리소스 관리 — iam:* 대신 실제 필요한 액션만 명시
        Sid    = "IAMManagement"
        Effect = "Allow"
        Action = [
          # 유저
          "iam:CreateUser", "iam:DeleteUser", "iam:GetUser",
          "iam:TagUser", "iam:UntagUser", "iam:ListUserTags", "iam:ListUsers",

          # 그룹
          "iam:CreateGroup", "iam:DeleteGroup", "iam:GetGroup", "iam:ListGroups",

          # 그룹 멤버십
          "iam:AddUserToGroup", "iam:RemoveUserFromGroup", "iam:ListGroupsForUser",

          # 그룹 정책 연결
          "iam:AttachGroupPolicy", "iam:DetachGroupPolicy", "iam:ListAttachedGroupPolicies",

          # 관리형 정책
          "iam:CreatePolicy", "iam:DeletePolicy",
          "iam:GetPolicy", "iam:GetPolicyVersion",
          "iam:CreatePolicyVersion", "iam:DeletePolicyVersion",
          "iam:ListPolicies", "iam:ListPolicyVersions", "iam:ListEntitiesForPolicy",

          # 유저 인라인 정책
          "iam:PutUserPolicy", "iam:DeleteUserPolicy",
          "iam:GetUserPolicy", "iam:ListUserPolicies",

          # 액세스 키
          "iam:CreateAccessKey", "iam:DeleteAccessKey",
          "iam:ListAccessKeys", "iam:GetAccessKeyLastUsed",

          # OIDC 프로바이더
          "iam:CreateOpenIDConnectProvider", "iam:DeleteOpenIDConnectProvider",
          "iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviders",
          "iam:TagOpenIDConnectProvider", "iam:ListOpenIDConnectProviderTags",

          # IAM 롤
          "iam:CreateRole", "iam:DeleteRole", "iam:GetRole",
          "iam:UpdateRole", "iam:UpdateAssumeRolePolicy",
          "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags", "iam:ListRoles",

          # 롤 인라인 정책
          "iam:PutRolePolicy", "iam:DeleteRolePolicy",
          "iam:GetRolePolicy", "iam:ListRolePolicies",

          # 롤 관리형 정책 연결
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",

          # 계정 패스워드 정책
          "iam:GetAccountPasswordPolicy",
          "iam:UpdateAccountPasswordPolicy",
          "iam:DeleteAccountPasswordPolicy"
        ]
        Resource = "*"
      }
    ]
  })
}

# ─────────────────────────────────────
# Output — GitHub Secrets 등록에 사용
# ─────────────────────────────────────
output "github_actions_role_arn" {
  description = "GitHub Secrets > AWS_ROLE_ARN 에 등록할 값"
  value       = aws_iam_role.github_actions.arn
}
