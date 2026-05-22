resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = []

  tags = {
    Name      = "github-actions-oidc"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role" "github_actions" {
  name        = "ilpumjinro-github-actions-role"
  description = "IAM Role for GitHub Actions Terraform execution via OIDC"

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
    Name      = "ilpumjinro-github-actions-role"
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role_policy" "github_actions_terraform" {
  name = "ilpumjinro-terraform-execution-policy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
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
        Sid    = "IAMManagement"
        Effect = "Allow"
        Action = [
          "iam:CreateUser",
          "iam:DeleteUser",
          "iam:GetUser",
          "iam:TagUser",
          "iam:UntagUser",
          "iam:ListUserTags",
          "iam:ListUsers",
          "iam:CreateGroup",
          "iam:DeleteGroup",
          "iam:GetGroup",
          "iam:ListGroups",
          "iam:AddUserToGroup",
          "iam:RemoveUserFromGroup",
          "iam:ListGroupsForUser",
          "iam:AttachGroupPolicy",
          "iam:DetachGroupPolicy",
          "iam:ListAttachedGroupPolicies",
          "iam:CreatePolicy",
          "iam:DeletePolicy",
          "iam:GetPolicy",
          "iam:GetPolicyVersion",
          "iam:CreatePolicyVersion",
          "iam:DeletePolicyVersion",
          "iam:ListPolicies",
          "iam:ListPolicyVersions",
          "iam:ListEntitiesForPolicy",
          "iam:PutUserPolicy",
          "iam:DeleteUserPolicy",
          "iam:GetUserPolicy",
          "iam:ListUserPolicies",
          "iam:CreateAccessKey",
          "iam:DeleteAccessKey",
          "iam:ListAccessKeys",
          "iam:GetAccessKeyLastUsed",
          "iam:CreateOpenIDConnectProvider",
          "iam:DeleteOpenIDConnectProvider",
          "iam:GetOpenIDConnectProvider",
          "iam:ListOpenIDConnectProviders",
          "iam:TagOpenIDConnectProvider",
          "iam:ListOpenIDConnectProviderTags",
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:GetInstanceProfile",
          "iam:UpdateRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRoleTags",
          "iam:ListRoles",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
          "iam:ListAttachedRolePolicies",
          "iam:GetAccountPasswordPolicy",
          "iam:UpdateAccountPasswordPolicy",
          "iam:DeleteAccountPasswordPolicy"
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2VPCManagement"
        Effect = "Allow"
        Action = [
          "ec2:CreateVpc",
          "ec2:DeleteVpc",
          "ec2:ModifyVpcAttribute",
          "ec2:DescribeVpcs",
          "ec2:DescribeVpcAttribute",
          "ec2:DescribePrefixLists",
          "ec2:CreateSubnet",
          "ec2:DeleteSubnet",
          "ec2:ModifySubnetAttribute",
          "ec2:DescribeSubnets",
          "ec2:CreateInternetGateway",
          "ec2:DeleteInternetGateway",
          "ec2:AttachInternetGateway",
          "ec2:DetachInternetGateway",
          "ec2:DescribeInternetGateways",
          "ec2:CreateRouteTable",
          "ec2:DeleteRouteTable",
          "ec2:CreateRoute",
          "ec2:DeleteRoute",
          "ec2:AssociateRouteTable",
          "ec2:DisassociateRouteTable",
          "ec2:DescribeRouteTables",
          "ec2:CreateVpcEndpoint",
          "ec2:DeleteVpcEndpoints",
          "ec2:DescribeVpcEndpoints",
          "ec2:ModifyVpcEndpoint",
          "ec2:CreateSecurityGroup",
          "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSecurityGroupRules",
          "ec2:CreateNatGateway",
          "ec2:DeleteNatGateway",
          "ec2:DescribeNatGateways",
          "ec2:AllocateAddress",
          "ec2:ReleaseAddress",
          "ec2:AssociateAddress",
          "ec2:DisassociateAddress",
          "ec2:DescribeAddresses",
          "ec2:CreateTags",
          "ec2:DeleteTags",
          "ec2:DescribeTags",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeAccountAttributes",
          "ec2:DescribeImages",
          "ec2:DescribeLaunchTemplates",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:DescribeVpcPeeringConnections",
          "ec2:DescribeAddressesAttribute"
        ]
        Resource = "*"
      },
      {
        Sid    = "CodeCommitManagement"
        Effect = "Allow"
        Action = [
          "codecommit:CreateRepository",
          "codecommit:DeleteRepository",
          "codecommit:GetRepository",
          "codecommit:ListRepositories",
          "codecommit:GitPull",
          "codecommit:GitPush",
          "codecommit:TagResource",
          "codecommit:UntagResource",
          "codecommit:ListTagsForResource"
        ]
        Resource = "*"
      },
      {
        Sid    = "ECRManagement"
        Effect = "Allow"
        Action = [
          "ecr:CreateRepository",
          "ecr:DeleteRepository",
          "ecr:DescribeRepositories",
          "ecr:PutLifecyclePolicy",
          "ecr:GetLifecyclePolicy",
          "ecr:DeleteLifecyclePolicy",
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          "ecr:BatchGetImage",
          "ecr:DescribeImages",
          "ecr:StartImageScan",
          "ecr:TagResource",
          "ecr:UntagResource",
          "ecr:ListTagsForResource"
        ]
        Resource = "*"
      },
      {
        Sid    = "EKSManagement"
        Effect = "Allow"
        Action = [
          "eks:CreateCluster",
          "eks:DeleteCluster",
          "eks:DescribeCluster",
          "eks:UpdateClusterConfig",
          "eks:UpdateClusterVersion",
          "eks:TagResource",
          "eks:UntagResource",
          "eks:ListTagsForResource",
          "eks:CreateNodegroup",
          "eks:DeleteNodegroup",
          "eks:DescribeNodegroup",
          "eks:UpdateNodegroupConfig",
          "eks:UpdateNodegroupVersion",
          "eks:CreateAddon",
          "eks:DeleteAddon",
          "eks:DescribeAddon",
          "eks:UpdateAddon",
          "eks:DescribeAddonVersions",
          "eks:ListAddons",
          "eks:CreatePodIdentityAssociation",
          "eks:DeletePodIdentityAssociation",
          "eks:DescribePodIdentityAssociation",
          "eks:UpdatePodIdentityAssociation",
          "eks:ListPodIdentityAssociations",
          "eks:CreateAccessEntry",
          "eks:DeleteAccessEntry",
          "eks:DescribeAccessEntry",
          "eks:UpdateAccessEntry",
          "eks:ListAccessEntries",
          "eks:AssociateAccessPolicy",
          "eks:DisassociateAccessPolicy",
          "eks:ListAssociatedAccessPolicies"
        ]
        Resource = "*"
      },
      {
        Sid    = "CodeBuildManagement"
        Effect = "Allow"
        Action = [
          "codebuild:CreateProject",
          "codebuild:DeleteProject",
          "codebuild:UpdateProject",
          "codebuild:BatchGetProjects",
          "codebuild:StartBuild",
          "codebuild:BatchGetBuilds",
          "codebuild:ListBuildsForProject"
        ]
        Resource = "*"
      },
      {
        Sid    = "PassEKSRoles"
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "eks.amazonaws.com",
              "ec2.amazonaws.com",
              "pods.eks.amazonaws.com",
              "codebuild.amazonaws.com"
            ]
          }
        }
      }
    ]
  })
}

output "github_actions_role_arn" {
  description = "GitHub Secrets AWS_ROLE_ARN value"
  value       = aws_iam_role.github_actions.arn
}
