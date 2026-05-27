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

resource "aws_eks_cluster" "ops" {
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
    Role = "internal-ops-cluster"
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
    aws_iam_role_policy_attachment.eks_vpc_resource_controller,
  ]
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

resource "aws_iam_role_policy_attachment" "eks_node_ebs_csi" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

# ──────────────────────────────────────────────────────────────────────────────
# Launch Template
# 노드 그룹에 우리가 만든 SG를 직접 붙이기 위해 필요
# EKS 자동 생성 SG 외에 financial-vpc2-eks-node-sg 추가 부착
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_launch_template" "eks_node" {
  name_prefix = "${var.eks_cluster_name}-node-"

  vpc_security_group_ids = [
    # EKS 클러스터 자동 생성 SG + 우리 SG 둘 다 부착
    aws_eks_cluster.ops.vpc_config[0].cluster_security_group_id,
    aws_security_group.eks_node.id,
  ]

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"  # IMDSv2 강제 (보안 강화)
    http_put_response_hop_limit = 2           # EKS 노드 필수값
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${var.eks_cluster_name}-node"
      Role = "internal-ops-node"
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_eks_node_group" "ops" {
  cluster_name    = aws_eks_cluster.ops.name
  node_group_name = "${var.eks_cluster_name}-general"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  capacity_type   = var.eks_node_capacity_type

  # launch_template 사용 시 instance_types, disk_size는
  # launch_template 또는 여기서 지정 (중복 불가)
  instance_types = var.eks_node_instance_types

  launch_template {
    id      = aws_launch_template.eks_node.id
    version = aws_launch_template.eks_node.latest_version
  }

  scaling_config {
    desired_size = var.eks_node_desired_size
    min_size     = var.eks_node_min_size
    max_size     = var.eks_node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    role = "internal-ops-general"
  }

  tags = {
    Name = "${var.eks_cluster_name}-general"
    Role = "internal-ops-node"
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_node_worker,
    aws_iam_role_policy_attachment.eks_node_cni,
    aws_iam_role_policy_attachment.eks_node_ecr,
    aws_iam_role_policy_attachment.eks_node_ebs_csi,
    aws_vpc_endpoint.ecr_api,
    aws_vpc_endpoint.ecr_dkr,
    aws_vpc_endpoint.eks,
    aws_vpc_endpoint.logs,
    aws_vpc_endpoint.s3,
    aws_vpc_endpoint.sts,
    aws_vpc_endpoint.ec2,
  ]
}

resource "aws_eks_addon" "vpc_cni" {
  cluster_name                = aws_eks_cluster.ops.name
  addon_name                  = "vpc-cni"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.ops]
}

resource "aws_eks_addon" "coredns" {
  cluster_name                = aws_eks_cluster.ops.name
  addon_name                  = "coredns"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.ops]
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name                = aws_eks_cluster.ops.name
  addon_name                  = "kube-proxy"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.ops]
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name                = aws_eks_cluster.ops.name
  addon_name                  = "aws-ebs-csi-driver"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [
    aws_eks_node_group.ops,
    aws_eks_pod_identity_association.ebs_csi,
    aws_vpc_endpoint.ec2,
    aws_vpc_endpoint.eks_auth,
    aws_vpc_endpoint.sts,
  ]
}

resource "aws_eks_addon" "pod_identity_agent" {
  cluster_name                = aws_eks_cluster.ops.name
  addon_name                  = "eks-pod-identity-agent"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.ops]
}

# ──────────────────────────────────────────────────────────────────────────────
# 모니터링 전용 Launch Template
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_launch_template" "eks_node_monitor" {
  name_prefix = "${var.eks_cluster_name}-monitor-"

  vpc_security_group_ids = [
    aws_eks_cluster.ops.vpc_config[0].cluster_security_group_id,
    aws_security_group.eks_node.id,
  ]

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${var.eks_cluster_name}-monitor-node"
      Role = "internal-ops-monitoring"
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# 모니터링 전용 노드 그룹
# - label: role=monitoring
# - taint: dedicated=monitoring:NoSchedule
#   → 일반 Pod는 이 노드에 스케줄링 불가
#   → Grafana/Thanos/Loki/Alertmanager만 올라올 수 있음
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_eks_node_group" "monitoring" {
  cluster_name    = aws_eks_cluster.ops.name
  node_group_name = "${var.eks_cluster_name}-monitoring"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = [aws_subnet.monitor_a.id]
  capacity_type   = var.eks_node_capacity_type
  instance_types  = var.eks_monitor_node_instance_types

  launch_template {
    id      = aws_launch_template.eks_node_monitor.id
    version = aws_launch_template.eks_node_monitor.latest_version
  }

  scaling_config {
    desired_size = var.eks_monitor_node_desired_size
    min_size     = var.eks_monitor_node_min_size
    max_size     = var.eks_monitor_node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  # 모니터링 전용 노드 label
  labels = {
    role = "monitoring"
  }

  # 일반 Pod 스케줄링 차단 taint
  taint {
    key    = "dedicated"
    value  = "monitoring"
    effect = "NO_SCHEDULE"
  }

  tags = {
    Name = "${var.eks_cluster_name}-monitoring"
    Role = "internal-ops-monitoring"
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_node_worker,
    aws_iam_role_policy_attachment.eks_node_cni,
    aws_iam_role_policy_attachment.eks_node_ecr,
    aws_iam_role_policy_attachment.eks_node_ebs_csi,
    aws_vpc_endpoint.ecr_api,
    aws_vpc_endpoint.ecr_dkr,
    aws_vpc_endpoint.eks,
    aws_vpc_endpoint.s3,
    aws_vpc_endpoint.sts,
  ]
}
