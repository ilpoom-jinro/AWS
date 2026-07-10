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

  encryption_config {
    resources = ["secrets"] # etcd에 저장되는 Kubernetes Secret 오브젝트 암호화
    provider {
      key_arn = var.kms_key_eks_arn
    }
  }

  tags = {
    Name = var.eks_cluster_name
    Role = "service-cluster"
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
    aws_iam_role_policy_attachment.eks_vpc_resource_controller,
    aws_iam_role_policy.eks_cluster_kms, # encryption_config 전에 KMS Grant 권한 확보 필수
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

# service 노드 Launch Template — IMDSv2 강제 + EBS CMK 암호화
# disk_size는 launch_template과 병용 불가 → block_device_mappings로 이전
resource "aws_launch_template" "eks_node_service" {
  name_prefix = "${var.eks_cluster_name}-node-"

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = var.eks_node_disk_size
      volume_type           = "gp3"
      encrypted             = true # 금융권 필수: 서비스 노드 루트 볼륨 CMK 암호화
      kms_key_id            = var.kms_key_eks_arn
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
    Name = "${var.eks_cluster_name}-node-lt"
  }
}

resource "aws_eks_node_group" "service" {
  cluster_name    = aws_eks_cluster.service.name
  node_group_name = "${var.eks_cluster_name}-general"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  instance_types  = var.eks_node_instance_types
  capacity_type   = var.eks_node_capacity_type
  # AL2023 명시 고정 — EKS 1.35는 ami_type 미지정 시 이미 AL2023가 기본값이나,
  # AWS 기본값 변경에 의존하지 않도록 명시. (SELinux permissive / IMDSv2-only / 최소 패키지 보안 기본값)
  ami_type = "AL2023_x86_64_STANDARD"
  # disk_size는 launch_template 사용 시 지정 불가 → launch template block_device_mappings로 이전

  scaling_config {
    # service general 노드는 외부 노출 데모앱 + Istio(istiod/ztunnel/gateway) 등이
    # 올라가 CPU가 빠듯함(2 vCPU 노드 단일 시 ~93% requests). CPU 확보와 HA,
    # Istio Gateway pod 수용을 위해 노드 수는 single_az_mode와 무관하게
    # eks_node_desired/min_size(기본 2)를 따른다. (ops general과 동일 패턴)
    desired_size = var.eks_node_desired_size
    min_size     = var.eks_node_min_size
    max_size     = var.eks_node_max_size
  }

  launch_template {
    id      = aws_launch_template.eks_node_service.id
    version = "$Latest"
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
    # CNI/kube-proxy 는 노드보다 먼저 설치돼야 노드가 Ready 가 된다.
    # (addon 이 node_group 을 depends_on 하면 노드 Ready ↔ CNI 설치 순환 데드락.)
    aws_eks_addon.vpc_cni,
    aws_eks_addon.kube_proxy,
    aws_iam_role_policy_attachment.eks_node_worker,
    aws_iam_role_policy_attachment.eks_node_cni,
    aws_iam_role_policy_attachment.eks_node_ecr,
  ]
}

# vpc-cni / kube-proxy 는 노드그룹보다 먼저 생성 (DaemonSet 이라 노드 0개에서도
# ACTIVE 로 수렴하고, 노드가 뜰 때 CNI 를 제공해 Ready 를 만든다). node_group 을
# depends_on 하면 순환 데드락 → NodeCreationFailure.
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
  # 노드그룹보다 먼저 생성 (vpc_cni 주석 참고). coredns 는 Deployment 라 노드 필요 → 그대로 뒤.
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
