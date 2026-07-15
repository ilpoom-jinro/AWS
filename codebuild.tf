locals {
  ecr_registry                         = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
  ansible_codebuild_image_repository   = "${local.ecr_registry}/${var.ansible_codebuild_image_repository_name}"
  internal_git_image_repository        = "${local.ecr_registry}/${var.internal_git_image_repository_name}"
  argocd_image_repository              = "${local.ecr_registry}/${var.argocd_image_repository_name}"
  argocd_redis_image_repository        = "${local.ecr_registry}/${var.argocd_redis_image_repository_name}"
  demo_backend_image_repository        = "${local.ecr_registry}/${var.demo_backend_image_repository_name}"
  demo_frontend_image_repository       = "${local.ecr_registry}/${var.demo_frontend_image_repository_name}"
  istio_image_repository_prefix        = "${local.ecr_registry}/${var.istio_image_repository_prefix}"
  cilium_image_repository              = "${local.ecr_registry}/financial/cilium"
  cilium_operator_image_repository     = "${local.ecr_registry}/financial/cilium-operator"
  cilium_envoy_image_repository        = "${local.ecr_registry}/financial/cilium-envoy"
  cilium_hubble_relay_image_repository = "${local.ecr_registry}/financial/cilium-hubble-relay"
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
          "ec2:DescribeInstances",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeVpcs"
        ]
        Resource = "*"
      },
      {
        Sid    = "RdsDescribe"
        Effect = "Allow"
        Action = [
          "rds:DescribeDBInstances"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchMetricsRead"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics"
        ]
        Resource = "*"
      },
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:financial-service-rds-password-*"
      },
      {
        # gitops-platform-sync가 서비스 ALB WAF web ACL ARN을 읽어 ingress
        # wafv2-acl-arn 어노테이션에 주입한다. 권한이 없으면 조용히(빈 값)
        # 어노테이션이 제거되어 WAF가 ALB에 부착되지 않는다.
        Sid    = "SsmReadWafAclArn"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter"
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/financial/waf/*"
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
      },
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
      name  = "DEMO_BACKEND_IMAGE"
      value = "${local.demo_backend_image_repository}:${var.demo_backend_image_tag}"
    }

    environment_variable {
      name  = "DEMO_FRONTEND_IMAGE"
      value = "${local.demo_frontend_image_repository}:${var.demo_frontend_image_tag}"
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
      name  = "CILIUM_IMAGE_REPOSITORY"
      value = local.cilium_image_repository
    }

    environment_variable {
      name  = "CILIUM_OPERATOR_IMAGE_REPOSITORY"
      value = local.cilium_operator_image_repository
    }

    environment_variable {
      name  = "CILIUM_ENVOY_IMAGE_REPOSITORY"
      value = local.cilium_envoy_image_repository
    }

    environment_variable {
      name  = "CILIUM_HUBBLE_RELAY_IMAGE_REPOSITORY"
      value = local.cilium_hubble_relay_image_repository
    }

    environment_variable {
      name  = "INTERNAL_GIT_ADMIN_USERNAME"
      value = var.internal_git_admin_username
    }

    environment_variable {
      name  = "INTERNAL_GIT_ADMIN_PASSWORD"
      value = random_password.internal_git_admin.result
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

resource "aws_codebuild_project" "gitops_bootstrap" {
  name          = var.gitops_bootstrap_codebuild_project_name
  description   = "Bootstraps internal GitOps repositories, demo-app manifests, and Argo CD Applications"
  service_role  = aws_iam_role.ansible_codebuild.arn
  build_timeout = 30

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
      value = random_password.internal_git_admin.result
      type  = "PLAINTEXT"
    }

    environment_variable {
      name  = "DEMO_BACKEND_IMAGE"
      value = "${local.demo_backend_image_repository}:${var.demo_backend_image_tag}"
    }

    environment_variable {
      name  = "DEMO_FRONTEND_IMAGE"
      value = "${local.demo_frontend_image_repository}:${var.demo_frontend_image_tag}"
    }

    environment_variable {
      name  = "TELEPORT_APP_JOIN_TOKEN"
      value = random_password.teleport_app_join_token.result
      type  = "PLAINTEXT"
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-gitops-bootstrap.yml")
  }

  vpc_config {
    vpc_id             = module.vpc2.vpc_id
    subnets            = module.vpc2.private_subnet_ids
    security_group_ids = [aws_security_group.ansible_codebuild.id, module.vpc2.eks_node_sg_id]
  }

  tags = {
    Name      = var.gitops_bootstrap_codebuild_project_name
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.ansible_codebuild,
    aws_eks_access_policy_association.ansible_codebuild_ops_admin,
    aws_eks_access_policy_association.ansible_codebuild_service_admin
  ]
}

resource "aws_codebuild_project" "cluster_status" {
  name          = var.cluster_status_codebuild_project_name
  description   = "Prints Ops EKS status for Argo CD, Istio, internal Git, and GitOps applications"
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
      value = module.vpc2.eks_cluster_name
    }

    environment_variable {
      name  = "SERVICE_EKS_CLUSTER_NAME"
      value = module.vpc1.eks_cluster_name
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-cluster-status.yml")
  }

  vpc_config {
    vpc_id             = module.vpc2.vpc_id
    subnets            = module.vpc2.private_subnet_ids
    security_group_ids = [aws_security_group.ansible_codebuild.id, module.vpc2.eks_node_sg_id]
  }

  tags = {
    Name      = var.cluster_status_codebuild_project_name
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.ansible_codebuild,
    aws_eks_access_policy_association.ansible_codebuild_ops_admin,
    aws_eks_access_policy_association.ansible_codebuild_service_admin
  ]
}

resource "aws_codebuild_project" "debug" {
  name          = var.debug_codebuild_project_name
  description   = "Runs debug commands from inside the Ops VPC"
  service_role  = aws_iam_role.ansible_codebuild.arn
  build_timeout = 10

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
      value = module.vpc2.eks_cluster_name
    }

    environment_variable {
      name  = "INTERNAL_GIT_ADMIN_USERNAME"
      value = var.internal_git_admin_username
    }

    environment_variable {
      name  = "INTERNAL_GIT_ADMIN_PASSWORD"
      value = random_password.internal_git_admin.result
      type  = "PLAINTEXT"
    }

    environment_variable {
      name  = "OPS_VPC_COMMAND"
      value = var.ops_vpc_command
      type  = "PLAINTEXT"
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-debug.yml")
  }

  vpc_config {
    vpc_id             = module.vpc2.vpc_id
    subnets            = module.vpc2.private_subnet_ids
    security_group_ids = [aws_security_group.ansible_codebuild.id, module.vpc2.eks_node_sg_id]
  }

  tags = {
    Name      = var.debug_codebuild_project_name
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.ansible_codebuild,
    aws_eks_access_policy_association.ansible_codebuild_ops_admin
  ]
}


resource "aws_codebuild_project" "mas_status" {
  name          = var.mas_status_codebuild_project_name
  description   = "Prints MAS UI and Teleport app-service status from inside the Ops VPC"
  service_role  = aws_iam_role.ansible_codebuild.arn
  build_timeout = 10

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
      value = module.vpc2.eks_cluster_name
    }

    environment_variable {
      name  = "FINOPS_NAMESPACE"
      value = "finops-mas"
    }

    environment_variable {
      name  = "TELEPORT_APP_NAMESPACE"
      value = "teleport-apps"
    }

    environment_variable {
      name  = "TELEPORT_APP_DEPLOYMENT"
      value = "teleport-app-service"
    }

    environment_variable {
      name  = "TELEPORT_APP_JOIN_TOKEN"
      value = ""
      type  = "PLAINTEXT"
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-mas-status.yml")
  }

  vpc_config {
    vpc_id             = module.vpc2.vpc_id
    subnets            = module.vpc2.private_subnet_ids
    security_group_ids = [aws_security_group.ansible_codebuild.id, module.vpc2.eks_node_sg_id]
  }

  tags = {
    Name      = var.mas_status_codebuild_project_name
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.ansible_codebuild,
    aws_eks_access_policy_association.ansible_codebuild_ops_admin
  ]
}

resource "aws_security_group" "service_cluster_status_codebuild" {
  name        = "financial-service-cluster-status-codebuild-sg"
  description = "CodeBuild security group for checking Service EKS workload status"
  vpc_id      = module.vpc1.vpc_id

  egress {
    description = "Allow HTTPS to private EKS API and AWS services through NAT"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name      = "financial-service-cluster-status-codebuild-sg"
    ManagedBy = "terraform"
  }
}

resource "aws_security_group_rule" "service_cluster_status_to_service_eks_api" {
  type                     = "ingress"
  description              = "Allow Service VPC status CodeBuild to access the private Service EKS API"
  security_group_id        = module.vpc1.eks_cluster_security_group_id
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.service_cluster_status_codebuild.id
}

resource "aws_codebuild_project" "service_cluster_status" {
  name          = var.service_cluster_status_codebuild_project_name
  description   = "Prints Service EKS status for Istio and demo-app from inside the Service VPC"
  service_role  = aws_iam_role.ansible_codebuild.arn
  build_timeout = 15

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
      name  = "SERVICE_EKS_CLUSTER_NAME"
      value = module.vpc1.eks_cluster_name
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-service-cluster-status.yml")
  }

  vpc_config {
    vpc_id             = module.vpc1.vpc_id
    subnets            = module.vpc1.private_subnet_ids
    security_group_ids = [aws_security_group.service_cluster_status_codebuild.id]
  }

  tags = {
    Name      = var.service_cluster_status_codebuild_project_name
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.ansible_codebuild,
    aws_eks_access_policy_association.ansible_codebuild_service_admin,
    aws_security_group_rule.service_cluster_status_to_service_eks_api
  ]
}

# GCP_sub DR workflows cannot reach the private Service EKS API directly.
# This fixed-buildspec project runs inside the Service VPC and accepts only the
# fence/unfence action through an environment-variable override.
resource "aws_codebuild_project" "dr_write_fence" {
  name          = var.dr_write_fence_codebuild_project_name
  description   = "Temporarily blocks stock-api database access for controlled DR switching"
  service_role  = aws_iam_role.ansible_codebuild.arn
  build_timeout = 15

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
      name  = "SERVICE_EKS_CLUSTER_NAME"
      value = module.vpc1.eks_cluster_name
    }

    environment_variable {
      name  = "DR_WRITE_FENCE_ACTION"
      value = "status"
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("buildspec-dr-write-fence.yml")
  }

  vpc_config {
    vpc_id             = module.vpc1.vpc_id
    subnets            = module.vpc1.private_subnet_ids
    security_group_ids = [aws_security_group.service_cluster_status_codebuild.id]
  }

  tags = {
    Name      = var.dr_write_fence_codebuild_project_name
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_iam_role_policy.ansible_codebuild,
    aws_eks_access_policy_association.ansible_codebuild_service_admin,
    aws_security_group_rule.service_cluster_status_to_service_eks_api
  ]
}
