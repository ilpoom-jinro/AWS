resource "aws_iam_role" "eks_cluster" {
  name = "${var.eks_cluster_name}-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "eks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-cluster-role"
  }
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy_attachment" "eks_vpc_resource_controller" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSVPCResourceController"
}

resource "aws_eks_cluster" "service" {
  name     = var.eks_cluster_name
  role_arn = aws_iam_role.eks_cluster.arn
  version  = var.eks_cluster_version

  vpc_config {
    subnet_ids              = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_group_ids      = [aws_security_group.eks_node.id]
    endpoint_private_access = true
    endpoint_public_access  = false
  }

  access_config {
    authentication_mode                         = "API_AND_CONFIG_MAP"
    bootstrap_cluster_creator_admin_permissions = true
  }

  enabled_cluster_log_types = var.eks_enabled_cluster_log_types

  tags = {
    Name = var.eks_cluster_name
    Role = "service-cluster"
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
    aws_iam_role_policy_attachment.eks_vpc_resource_controller,
  ]
}

resource "aws_security_group_rule" "eks_cluster_api_from_ops" {
  type              = "ingress"
  description       = "Allow Ops VPC automation to access the private EKS API"
  security_group_id = aws_eks_cluster.service.vpc_config[0].cluster_security_group_id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [var.vpc2_cidr]
}

resource "aws_iam_role" "eks_node" {
  name = "${var.eks_cluster_name}-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-node-role"
  }
}

resource "aws_iam_role_policy_attachment" "eks_node_worker" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "eks_node_cni" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "eks_node_ecr" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role" "ebs_csi" {
  name = "${var.eks_cluster_name}-ebs-csi-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowEksAuthToAssumeRoleForPodIdentity"
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
      Action = [
        "sts:AssumeRole",
        "sts:TagSession"
      ]
      Condition = {
        StringEquals = {
          "aws:RequestTag/kubernetes-namespace"       = "kube-system"
          "aws:RequestTag/kubernetes-service-account" = "ebs-csi-controller-sa"
        }
      }
    }]
  })

  tags = {
    Name = "${var.eks_cluster_name}-ebs-csi-role"
  }
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_node_group" "service" {
  cluster_name    = aws_eks_cluster.service.name
  node_group_name = "${var.eks_cluster_name}-general"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  instance_types  = var.eks_node_instance_types
  capacity_type   = var.eks_node_capacity_type
  disk_size       = var.eks_node_disk_size

  scaling_config {
    desired_size = var.single_az_mode ? 1 : var.eks_node_desired_size
    min_size     = var.single_az_mode ? 1 : var.eks_node_min_size
    max_size     = var.eks_node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    role = "service-general"
  }

  tags = {
    Name = "${var.eks_cluster_name}-general"
    Role = "service-node"
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_node_worker,
    aws_iam_role_policy_attachment.eks_node_cni,
    aws_iam_role_policy_attachment.eks_node_ecr,
  ]
}

resource "aws_eks_addon" "vpc_cni" {
  cluster_name                = aws_eks_cluster.service.name
  addon_name                  = "vpc-cni"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  # DISABLE_TCP_EARLY_DEMUX=true: 보조 ENI에 있는 파드로 외부(ALB/NLB)에서 오는
  # TCP 헬스체크가 커널 TCP early demux로 인해 노드 소켓으로 잘못 라우팅되는 문제
  # 해결. 이 설정이 false면 노드 내부 kube-probe는 통과하지만 외부 LB 헬스체크는
  # 파드(nginx)에 도달하지 못해 항상 unhealthy가 됨. ALB target-type:ip 노출에 필수.
  configuration_values = jsonencode({
    init = {
      env = {
        DISABLE_TCP_EARLY_DEMUX = "true"
      }
    }
  })

  depends_on = [aws_eks_node_group.service]
}

resource "aws_eks_addon" "coredns" {
  cluster_name                = aws_eks_cluster.service.name
  addon_name                  = "coredns"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.service]
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name                = aws_eks_cluster.service.name
  addon_name                  = "kube-proxy"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.service]
}

resource "aws_eks_addon" "pod_identity_agent" {
  cluster_name                = aws_eks_cluster.service.name
  addon_name                  = "eks-pod-identity-agent"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.service]
}

resource "aws_eks_pod_identity_association" "ebs_csi" {
  cluster_name    = aws_eks_cluster.service.name
  namespace       = "kube-system"
  service_account = "ebs-csi-controller-sa"
  role_arn        = aws_iam_role.ebs_csi.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy_attachment.ebs_csi,
  ]
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name                = aws_eks_cluster.service.name
  addon_name                  = "aws-ebs-csi-driver"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [
    aws_eks_node_group.service,
    aws_eks_pod_identity_association.ebs_csi,
  ]
}
