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

resource "aws_iam_role" "ebs_csi" {
  name = "${var.eks_cluster_name}-ebs-csi-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
      Action = [
        "sts:AssumeRole",
        "sts:TagSession"
      ]
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

# ops 노드그룹 launch template — IMDSv2 강제 및 hop_limit 제한
resource "aws_launch_template" "eks_node_ops" {
  name_prefix = "financial-ops-eks-node-ops-"

  # 기존 aws_eks_node_group.ops의 disk_size = var.eks_node_disk_size (30GiB)를 여기로 이동
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = var.eks_node_disk_size
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "enabled"
  }

  tags = {
    Name = "financial-ops-eks-node-ops-lt"
  }
}

resource "aws_eks_node_group" "ops" {
  cluster_name    = aws_eks_cluster.ops.name
  node_group_name = "${var.eks_cluster_name}-general"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  instance_types  = var.eks_node_instance_types
  capacity_type   = var.eks_node_capacity_type

  scaling_config {
    desired_size = var.eks_node_desired_size
    min_size     = var.eks_node_min_size
    max_size     = var.eks_node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  launch_template {
    id      = aws_launch_template.eks_node_ops.id
    version = "$Latest"
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
    aws_vpc_endpoint.eks_auth,
    aws_vpc_endpoint.logs,
    aws_vpc_endpoint.s3,
    aws_vpc_endpoint.sts,
    aws_vpc_endpoint.ec2,
  ]
}

# ──────────────────────────────────────────────────────────────────────────────
# Teleport — EKS 접근 (VPC3 Teleport kube service가 EKS API 프록시)
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_eks_access_entry" "teleport" {
  cluster_name  = aws_eks_cluster.ops.name
  principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/financial-vpc3-teleport-ec2-role"
  type          = "STANDARD"

  tags = {
    Name = "teleport-kube-proxy"
  }
}

resource "aws_eks_access_policy_association" "teleport_admin" {
  cluster_name  = aws_eks_cluster.ops.name
  principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/financial-vpc3-teleport-ec2-role"
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.teleport]
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

resource "aws_eks_pod_identity_association" "ebs_csi" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "kube-system"
  service_account = "ebs-csi-controller-sa"
  role_arn        = aws_iam_role.ebs_csi.arn

  depends_on = [
    aws_eks_addon.pod_identity_agent,
    aws_iam_role_policy_attachment.ebs_csi,
  ]
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
    http_put_response_hop_limit = 1
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

  labels = {
    role = "monitoring"
  }

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
