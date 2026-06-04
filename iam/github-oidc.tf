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

# ────────────────────────────────────────────────────────────────────────────
# Policy 1: IAM / Terraform State / PassRole / ServiceLinkedRole
# ────────────────────────────────────────────────────────────────────────────
resource "aws_iam_policy" "github_actions_iam" {
  name        = "ilpumjinro-github-actions-iam-policy"
  description = "Terraform state access, IAM management, PassRole, and service-linked role creation for GitHub Actions"

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
          "iam:TagPolicy",
          "iam:UntagPolicy",
          "iam:ListPolicyTags",
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
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:TagInstanceProfile",
          "iam:UntagInstanceProfile",
          "iam:ListInstanceProfiles",
          "iam:ListInstanceProfileTags",
          "iam:ListInstanceProfilesForRole",
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
        Sid    = "PassEKSRoles"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "eks.amazonaws.com",
              "ec2.amazonaws.com",
              "pods.eks.amazonaws.com",
              "codebuild.amazonaws.com",
              "config.amazonaws.com",
              "cloudtrail.amazonaws.com"
            ]
          }
        }
      },
      {
        # Access Analyzer 최초 생성 시 AWS가 자동으로 Service Linked Role을 만듦
        # AWSServiceRoleForAccessAnalyzer 생성 권한이 없으면 CreateAnalyzer 403 발생
        Sid      = "CreateServiceLinkedRoles"
        Effect   = "Allow"
        Action   = ["iam:CreateServiceLinkedRole"]
        Resource = "arn:aws:iam::*:role/aws-service-role/access-analyzer.amazonaws.com/AWSServiceRoleForAccessAnalyzer"
        Condition = {
          StringEquals = {
            "iam:AWSServiceName" = "access-analyzer.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = {
    Name      = "ilpumjinro-github-actions-iam-policy"
    ManagedBy = "terraform"
  }
}

# ────────────────────────────────────────────────────────────────────────────
# Policy 2: EC2 / VPC / EKS / ECR / CodeBuild
# ────────────────────────────────────────────────────────────────────────────
resource "aws_iam_policy" "github_actions_infra" {
  name        = "ilpumjinro-github-actions-infra-policy"
  description = "EC2/VPC, EKS, ECR, and CodeBuild management for GitHub Actions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
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
          "ec2:DescribeAddressesAttribute",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceAttribute",
          "ec2:DescribeInstanceCreditSpecifications",
          "ec2:DescribeIamInstanceProfileAssociations",
          "ec2:DescribeInstanceTypes",
          "ec2:RunInstances",
          "ec2:TerminateInstances",
          "ec2:StartInstances",
          "ec2:StopInstances",
          "ec2:RebootInstances",
          "ec2:ModifyInstanceAttribute",
          "ec2:AssociateIamInstanceProfile",
          "ec2:DisassociateIamInstanceProfile",
          "ec2:ReplaceIamInstanceProfileAssociation",
          "ec2:DescribeVolumes",
          "ec2:DescribeVolumesModifications",
          "ec2:DescribeVpcPeeringConnections",
          "ec2:CreateVpcPeeringConnection",
          "ec2:AcceptVpcPeeringConnection",
          "ec2:DeleteVpcPeeringConnection",
          "ec2:ModifyVpcPeeringConnectionOptions",
          "ec2:CreateTags",
          "ec2:DeleteTags",
          "ec2:DescribeTags",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeAccountAttributes",
          "ec2:DescribeImages",
          "ec2:CreateLaunchTemplate",
          "ec2:CreateLaunchTemplateVersion",
          "ec2:DeleteLaunchTemplate",
          "ec2:DeleteLaunchTemplateVersions",
          "ec2:DescribeLaunchTemplates",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:ModifyLaunchTemplate"
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
          "eks:DescribeUpdate",
          "eks:ListUpdates",
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
      }
    ]
  })

  tags = {
    Name      = "ilpumjinro-github-actions-infra-policy"
    ManagedBy = "terraform"
  }
}

# ────────────────────────────────────────────────────────────────────────────
# Policy 3: CloudWatch / CloudTrail / SNS / EventBridge / S3 / KMS / Config / AccessAnalyzer
# ────────────────────────────────────────────────────────────────────────────
resource "aws_iam_policy" "github_actions_security" {
  name        = "ilpumjinro-github-actions-security-policy"
  description = "Observability, security, and compliance service management for GitHub Actions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogsManagement"
        Effect = "Allow"
        Action = [
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:PutRetentionPolicy",
          "logs:ListTagsLogGroup",
          "logs:TagLogGroup",
          "logs:UntagLogGroup",
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:PutMetricFilter",
          "logs:DeleteMetricFilter",
          "logs:DescribeMetricFilters"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudTrailManagement"
        Effect = "Allow"
        Action = [
          "cloudtrail:DescribeTrails",
          "cloudtrail:GetTrail",
          "cloudtrail:GetTrailStatus",
          "cloudtrail:GetEventSelectors",
          "cloudtrail:PutEventSelectors",
          "cloudtrail:UpdateTrail",
          "cloudtrail:AddTags",
          "cloudtrail:RemoveTags",
          "cloudtrail:ListTags"
        ]
        Resource = "*"
      },
      {
        Sid    = "SNSManagement"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic",
          "sns:DeleteTopic",
          "sns:GetTopicAttributes",
          "sns:SetTopicAttributes",
          "sns:ListTopics",
          "sns:TagResource",
          "sns:UntagResource",
          "sns:ListTagsForResource",
          "sns:GetSubscriptionAttributes",
          "sns:SetSubscriptionAttributes"
        ]
        Resource = "*"
      },
      {
        Sid    = "EventBridgeManagement"
        Effect = "Allow"
        Action = [
          "events:PutRule",
          "events:DeleteRule",
          "events:DescribeRule",
          "events:EnableRule",
          "events:DisableRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:ListTargetsByRule",
          "events:ListRules",
          "events:TagResource",
          "events:UntagResource",
          "events:ListTagsForResource"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchAlarmsManagement"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:DescribeAlarmsForMetric",
          "cloudwatch:EnableAlarmActions",
          "cloudwatch:DisableAlarmActions",
          "cloudwatch:ListTagsForResource",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource"
        ]
        Resource = "*"
      },
      {
        Sid    = "S3BucketManagement"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:DeleteBucket",
          "s3:GetBucketAcl",
          "s3:GetBucketPolicy",
          "s3:PutBucketPolicy",
          "s3:DeleteBucketPolicy",
          "s3:GetBucketPublicAccessBlock",
          "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketVersioning",
          "s3:GetBucketLogging",
          "s3:GetBucketLocation",
          "s3:GetBucketTagging",
          "s3:PutBucketTagging",
          "s3:ListBucket",
          "s3:GetBucketCORS",
          "s3:GetBucketWebsite",
          "s3:GetAccelerateConfiguration",
          "s3:GetBucketRequestPayment",
          "s3:GetLifecycleConfiguration",
          "s3:GetEncryptionConfiguration",
          "s3:GetBucketObjectLockConfiguration",
          "s3:GetBucketOwnershipControls",
          "s3:GetReplicationConfiguration",
          "s3:GetBucketNotification",
          "s3:GetAnalyticsConfiguration",
          "s3:GetMetricsConfiguration",
          "s3:GetInventoryConfiguration",
          "s3:GetIntelligentTieringConfiguration"
        ]
        Resource = "*"
      },
      {
        Sid    = "KMSManagement"
        Effect = "Allow"
        Action = [
          "kms:CreateKey",
          "kms:DescribeKey",
          "kms:EnableKey",
          "kms:DisableKey",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:ListResourceTags",
          "kms:EnableKeyRotation",
          "kms:DisableKeyRotation",
          "kms:GetKeyRotationStatus",
          "kms:PutKeyPolicy",
          "kms:GetKeyPolicy",
          "kms:ScheduleKeyDeletion",
          "kms:CancelKeyDeletion",
          "kms:ListKeys",
          "kms:ListAliases",
          "kms:CreateAlias",
          "kms:UpdateAlias",
          "kms:DeleteAlias",
          "kms:UpdateKeyDescription"
        ]
        Resource = "*"
      },
      {
        Sid    = "ConfigManagement"
        Effect = "Allow"
        Action = [
          "config:PutConfigurationRecorder",
          "config:DeleteConfigurationRecorder",
          "config:DescribeConfigurationRecorders",
          "config:DescribeConfigurationRecorderStatus",
          "config:StartConfigurationRecorder",
          "config:StopConfigurationRecorder",
          "config:PutDeliveryChannel",
          "config:DeleteDeliveryChannel",
          "config:DescribeDeliveryChannels",
          "config:DescribeDeliveryChannelStatus",
          "config:PutConfigRule",
          "config:DeleteConfigRule",
          "config:DescribeConfigRules",
          "config:DescribeConfigRuleEvaluationStatus",
          "config:TagResource",
          "config:UntagResource",
          "config:ListTagsForResource"
        ]
        Resource = "*"
      },
      {
        Sid    = "AccessAnalyzerManagement"
        Effect = "Allow"
        Action = [
          "access-analyzer:CreateAnalyzer",
          "access-analyzer:DeleteAnalyzer",
          "access-analyzer:GetAnalyzer",
          "access-analyzer:ListAnalyzers",
          "access-analyzer:TagResource",
          "access-analyzer:UntagResource",
          "access-analyzer:ListTagsForResource"
        ]
        Resource = "*"
      }
    ]
  })

  tags = {
    Name      = "ilpumjinro-github-actions-security-policy"
    ManagedBy = "terraform"
  }
}

# ────────────────────────────────────────────────────────────────────────────
# Role attachments — 3개 관리형 정책을 prod Role에 연결
# ────────────────────────────────────────────────────────────────────────────
resource "aws_iam_role_policy_attachment" "github_actions_iam" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.github_actions_iam.arn
}

resource "aws_iam_role_policy_attachment" "github_actions_infra" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.github_actions_infra.arn
}

resource "aws_iam_role_policy_attachment" "github_actions_security" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.github_actions_security.arn
}

output "github_actions_role_arn" {
  description = "GitHub Secrets AWS_ROLE_ARN value"
  value       = aws_iam_role.github_actions.arn
}
