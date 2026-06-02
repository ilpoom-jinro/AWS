locals {
  ecr_registry                       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
  ansible_codebuild_image_repository = "${local.ecr_registry}/${var.ansible_codebuild_image_repository_name}"
  internal_git_image_repository      = "${local.ecr_registry}/${var.internal_git_image_repository_name}"
  argocd_image_repository            = "${local.ecr_registry}/${var.argocd_image_repository_name}"
  argocd_redis_image_repository      = "${local.ecr_registry}/${var.argocd_redis_image_repository_name}"
  prometheus_image_repository        = "${local.ecr_registry}/${var.prometheus_image_repository_name}"
  mas_runtime_image_repository       = "${local.ecr_registry}/${var.mas_runtime_image_repository_name}"
  mas_base_image_repository          = "${local.ecr_registry}/${var.mas_base_image_repository_name}"
  mas_orchestrator_image_repository  = "${local.ecr_registry}/${var.mas_orchestrator_image_repository_name}"
  mas_observer_image_repository      = "${local.ecr_registry}/${var.mas_observer_image_repository_name}"
  mas_analyzer_image_repository      = "${local.ecr_registry}/${var.mas_analyzer_image_repository_name}"
  mas_ui_image_repository            = "${local.ecr_registry}/${var.mas_ui_image_repository_name}"
  istio_image_repository_prefix      = "${local.ecr_registry}/${var.istio_image_repository_prefix}"
  teleport_image_repository          = "${local.ecr_registry}/${var.teleport_image_repository_name}"
}

resource "aws_security_group" "ansible_codebuild" {
  name        = "financial-ansible-codebuild-sg"
  description = "CodeBuild security group for running Ansible against private EKS endpoints"
  vpc_id      = module.vpc2.vpc_id

  egress {
    description = "Allow internal HTTPS to VPC endpoints and private EKS APIs"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [module.vpc2.vpc_cidr, module.vpc1.vpc_cidr]
  }

  egress {
    description = "Allow internal Kubernetes node/API traffic when required"
    from_port   = 1024
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = [module.vpc2.vpc_cidr, module.vpc1.vpc_cidr]
  }

  tags = {
    Name      = "financial-ansible-codebuild-sg"
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role" "ansible_codebuild" {
  name        = "financial-ansible-codebuild-role"
  description = "Runs Ansible bootstrap for the private Ops EKS cluster"

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
    Name      = "financial-ansible-codebuild-role"
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role_policy" "ansible_codebuild" {
  name = "financial-ansible-codebuild-policy"
  role = aws_iam_role.ansible_codebuild.id

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
        Sid    = "EcrPullRuntimeImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*"
      },
      {
        Sid    = "EksDescribe"
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster"
        ]
        Resource = [
          module.vpc1.eks_cluster_arn,
          module.vpc2.eks_cluster_arn
        ]
      },
      {
        Sid    = "VpcNetworkInterfaces"
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DeleteNetworkInterface",
          "ec2:DescribeDhcpOptions",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeVpcs"
        ]
        Resource = "*"
      },
      {
        Sid    = "CodeBuildNetworkInterfacePermission"
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterfacePermission"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "ec2:AuthorizedService" = "codebuild.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_eks_access_entry" "ansible_codebuild_ops" {
  cluster_name  = module.vpc2.eks_cluster_name
  principal_arn = aws_iam_role.ansible_codebuild.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "ansible_codebuild_ops_admin" {
  cluster_name  = module.vpc2.eks_cluster_name
  principal_arn = aws_iam_role.ansible_codebuild.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.ansible_codebuild_ops]
}

resource "aws_eks_access_entry" "ansible_codebuild_service" {
  cluster_name  = module.vpc1.eks_cluster_name
  principal_arn = aws_iam_role.ansible_codebuild.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "ansible_codebuild_service_admin" {
  cluster_name  = module.vpc1.eks_cluster_name
  principal_arn = aws_iam_role.ansible_codebuild.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.ansible_codebuild_service]
}

resource "aws_codebuild_project" "ansible_bootstrap" {
  name          = "financial-ansible-bootstrap"
  description   = "Runs Ansible against the private Internal Ops EKS cluster"
  service_role  = aws_iam_role.ansible_codebuild.arn
  build_timeout = 60

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = coalesce(var.ansible_codebuild_image, "${local.ansible_codebuild_image_repository}:latest")
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "SERVICE_ROLE"

    environment_variable {
      name  = "ANSIBLE_CONFIG"
      value = "/workspace/ansible/ansible.cfg"
    }

    environment_variable {
      name  = "INTERNAL_GIT_IMAGE"
      value = "${local.internal_git_image_repository}:latest"
    }

    environment_variable {
      name  = "ARGOCD_IMAGE_REPOSITORY"
      value = local.argocd_image_repository
    }

    environment_variable {
      name  = "ARGOCD_IMAGE_TAG"
      value = var.argocd_image_tag
    }

    environment_variable {
      name  = "ARGOCD_REDIS_IMAGE_REPOSITORY"
      value = local.argocd_redis_image_repository
    }

    environment_variable {
      name  = "ARGOCD_REDIS_IMAGE_TAG"
      value = var.argocd_redis_image_tag
    }

    environment_variable {
      name  = "PROMETHEUS_IMAGE_REPOSITORY"
      value = local.prometheus_image_repository
    }

    environment_variable {
      name  = "PROMETHEUS_IMAGE_TAG"
      value = var.prometheus_image_tag
    }

    environment_variable {
      name  = "MAS_RUNTIME_IMAGE"
      value = "${local.mas_runtime_image_repository}:${var.mas_runtime_image_tag}"
    }

    environment_variable {
      name  = "MAS_ORCHESTRATOR_IMAGE"
      value = "${local.mas_orchestrator_image_repository}:${var.mas_agent_image_tag}"
    }

    environment_variable {
      name  = "MAS_OBSERVER_IMAGE"
      value = "${local.mas_observer_image_repository}:${var.mas_agent_image_tag}"
    }

    environment_variable {
      name  = "MAS_ANALYZER_IMAGE"
      value = "${local.mas_analyzer_image_repository}:${var.mas_agent_image_tag}"
    }

    environment_variable {
      name  = "MAS_UI_IMAGE"
      value = "${local.mas_ui_image_repository}:${var.mas_agent_image_tag}"
    }

    environment_variable {
      name  = "TELEPORT_APP_IMAGE"
      value = "${local.teleport_image_repository}:latest"
    }

    environment_variable {
      name  = "ISTIO_IMAGE_HUB"
      value = local.istio_image_repository_prefix
    }

    environment_variable {
      name  = "ISTIO_IMAGE_TAG"
      value = var.istio_image_tag
    }

    environment_variable {
      name  = "INTERNAL_GIT_ADMIN_USERNAME"
      value = var.internal_git_admin_username
    }

    environment_variable {
      name  = "INTERNAL_GIT_ADMIN_PASSWORD"
      value = var.internal_git_admin_password
      type  = "PLAINTEXT"
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-ansible.yml")
  }

  vpc_config {
    vpc_id             = module.vpc2.vpc_id
    subnets            = module.vpc2.private_subnet_ids
    security_group_ids = [aws_security_group.ansible_codebuild.id, module.vpc2.eks_node_sg_id]
  }

  tags = {
    Name      = "financial-ansible-bootstrap"
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.ansible_codebuild
  ]
}

resource "aws_codebuild_project" "mas_gitops_sync" {
  name          = var.mas_gitops_sync_codebuild_project_name
  description   = "Syncs MAS Kubernetes manifests into the internal GitOps repository for Argo CD"
  service_role  = aws_iam_role.ansible_codebuild.arn
  build_timeout = 20

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = coalesce(var.ansible_codebuild_image, "${local.ansible_codebuild_image_repository}:latest")
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "SERVICE_ROLE"

    environment_variable {
      name  = "ANSIBLE_CONFIG"
      value = "/workspace/ansible/ansible.cfg"
    }

    environment_variable {
      name  = "INTERNAL_GIT_ADMIN_USERNAME"
      value = var.internal_git_admin_username
    }

    environment_variable {
      name  = "INTERNAL_GIT_ADMIN_PASSWORD"
      value = var.internal_git_admin_password
      type  = "PLAINTEXT"
    }

    environment_variable {
      name  = "MAS_ORCHESTRATOR_IMAGE"
      value = "${local.mas_orchestrator_image_repository}:${var.mas_agent_image_tag}"
    }

    environment_variable {
      name  = "MAS_OBSERVER_IMAGE"
      value = "${local.mas_observer_image_repository}:${var.mas_agent_image_tag}"
    }

    environment_variable {
      name  = "MAS_ANALYZER_IMAGE"
      value = "${local.mas_analyzer_image_repository}:${var.mas_agent_image_tag}"
    }

    environment_variable {
      name  = "MAS_UI_IMAGE"
      value = "${local.mas_ui_image_repository}:${var.mas_agent_image_tag}"
    }

    environment_variable {
      name  = "TELEPORT_APP_IMAGE"
      value = "${local.teleport_image_repository}:latest"
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-mas-gitops-sync.yml")
  }

  vpc_config {
    vpc_id             = module.vpc2.vpc_id
    subnets            = module.vpc2.private_subnet_ids
    security_group_ids = [aws_security_group.ansible_codebuild.id, module.vpc2.eks_node_sg_id]
  }

  tags = {
    Name      = var.mas_gitops_sync_codebuild_project_name
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.ansible_codebuild,
    aws_eks_access_policy_association.ansible_codebuild_ops_admin
  ]
}

resource "aws_codebuild_project" "mas_analyze" {
  name          = var.mas_analyze_codebuild_project_name
  description   = "Invokes the MAS orchestrator analyze API from inside the Ops VPC"
  service_role  = aws_iam_role.ansible_codebuild.arn
  build_timeout = 20

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = coalesce(var.ansible_codebuild_image, "${local.ansible_codebuild_image_repository}:latest")
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
      name  = "MAS_NAMESPACE"
      value = "mas"
    }

    environment_variable {
      name  = "MAS_ORCHESTRATOR_SERVICE"
      value = "mas-orchestrator"
    }

    environment_variable {
      name  = "MAS_ANALYZE_NAMESPACE"
      value = "argocd"
    }

    environment_variable {
      name  = "MAS_ANALYZE_PROMPT"
      value = "Kubernetes 리소스 상태를 분석하고, 문제가 있으면 원인과 다음 확인 작업을 알려줘."
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-mas-analyze.yml")
  }

  vpc_config {
    vpc_id             = module.vpc2.vpc_id
    subnets            = module.vpc2.private_subnet_ids
    security_group_ids = [aws_security_group.ansible_codebuild.id, module.vpc2.eks_node_sg_id]
  }

  tags = {
    Name      = var.mas_analyze_codebuild_project_name
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.ansible_codebuild,
    aws_eks_access_policy_association.ansible_codebuild_ops_admin
  ]
}
