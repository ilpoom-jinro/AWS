data "aws_caller_identity" "current" {}

locals {
  manifest_updater_image = coalesce(
    var.manifest_updater_image,
    "${local.ecr_registry}/${var.manifest_updater_image_repository_name}:${var.manifest_updater_image_tag}"
  )
}

resource "aws_security_group" "manifest_updater_codebuild" {
  name        = "financial-manifest-updater-codebuild-sg"
  description = "CodeBuild security group for updating internal GitOps manifests"
  vpc_id      = module.vpc2.vpc_id

  egress {
    description = "Allow HTTPS to private AWS endpoints and EKS API"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [module.vpc2.vpc_cidr]
  }

  egress {
    description = "Allow Kubernetes API port-forward traffic through private cluster networking"
    from_port   = 1024
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = [module.vpc2.vpc_cidr]
  }

  tags = {
    Name      = "financial-manifest-updater-codebuild-sg"
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role" "manifest_updater_codebuild" {
  name        = "financial-manifest-updater-codebuild-role"
  description = "Updates internal GitOps manifests from app deployment workflows"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "codebuild.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name      = "financial-manifest-updater-codebuild-role"
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role_policy" "manifest_updater_codebuild" {
  name = "financial-manifest-updater-codebuild-policy"
  role = aws_iam_role.manifest_updater_codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Logs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      },
      {
        Sid    = "PullRuntimeImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetAuthorizationToken",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = "*"
      },
      {
        Sid    = "EksAccess"
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster"
        ]
        Resource = "*"
      },
      {
        Sid    = "BulkImageUpdatePayloadRead"
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "arn:aws:s3:::ilpumjinro-terraform-state-v4/mas-manifest-updates/*"
      },
      {
        Sid    = "VpcNetworkInterfaces"
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:CreateNetworkInterfacePermission",
          "ec2:DeleteNetworkInterface",
          "ec2:DescribeDhcpOptions",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeVpcs"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_eks_access_entry" "manifest_updater_ops" {
  cluster_name  = var.ops_eks_cluster_name
  principal_arn = aws_iam_role.manifest_updater_codebuild.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "manifest_updater_ops_admin" {
  cluster_name  = var.ops_eks_cluster_name
  principal_arn = aws_iam_role.manifest_updater_codebuild.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.manifest_updater_ops]
}

resource "aws_codebuild_project" "manifest_updater" {
  name          = var.manifest_updater_codebuild_project_name
  description   = "Updates image tags in the internal GitOps repository for Argo CD"
  service_role  = aws_iam_role.manifest_updater_codebuild.arn
  build_timeout = 15

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = local.manifest_updater_image
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "SERVICE_ROLE"

    environment_variable {
      name  = "AWS_REGION"
      value = var.aws_region
    }

    environment_variable {
      name  = "OPS_EKS_CLUSTER_NAME"
      value = var.ops_eks_cluster_name
    }

    environment_variable {
      name  = "INTERNAL_GIT_NAMESPACE"
      value = var.internal_git_namespace
    }

    environment_variable {
      name  = "INTERNAL_GIT_SERVICE_NAME"
      value = var.internal_git_service_name
    }

    environment_variable {
      name  = "INTERNAL_GIT_HTTP_PORT"
      value = tostring(var.internal_git_http_port)
    }

    environment_variable {
      name  = "INTERNAL_GIT_ORG"
      value = var.internal_git_org
    }

    environment_variable {
      name  = "INTERNAL_GIT_REPO"
      value = var.internal_git_repo
    }

    environment_variable {
      name  = "INTERNAL_GIT_USERNAME"
      value = var.internal_git_admin_username
    }

    environment_variable {
      name  = "INTERNAL_GIT_PASSWORD"
      value = random_password.internal_git_admin.result
      type  = "PLAINTEXT"
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-manifest-updater.yml")
  }

  vpc_config {
    vpc_id             = module.vpc2.vpc_id
    subnets            = module.vpc2.private_subnet_ids
    security_group_ids = [aws_security_group.manifest_updater_codebuild.id, module.vpc2.eks_node_sg_id]
  }

  tags = {
    Name      = var.manifest_updater_codebuild_project_name
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.manifest_updater_codebuild,
    aws_eks_access_policy_association.manifest_updater_ops_admin
  ]
}
