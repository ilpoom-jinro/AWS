# ──────────────────────────────────────────────────────────────────────────────
# VPC 2 — Security Groups
# ──────────────────────────────────────────────────────────────────────────────

# ── EKS Node Security Group ───────────────────────────────────────────────────

resource "aws_security_group" "eks_node" {
  name        = "financial-vpc2-eks-node-sg"
  description = "EKS Node Security Group - Allow traffic within node group and from Teleport"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Allow inter-node communication"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  ingress {
    description = "Allow SSH from Teleport (VPC3)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.vpc3_cidr]
  }

  ingress {
    description = "Allow HTTPS from Teleport (VPC3) - EKS API kube proxy"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc3_cidr]
  }

  ingress {
    description = "Allow inbound from VPC 1 service (Peering)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc1_cidr]
  }

  egress {
    description = "Allow HTTPS to VPC Endpoints"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.20.0.0/16"]
  }

  egress {
    description = "Allow all outbound within node group (CNI, kubelet)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  egress {
    description = "Allow outbound to Peering VPCs"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc1_cidr, var.vpc3_cidr]
  }

  tags = {
    Name = "financial-vpc2-eks-node-sg"
  }
}

# ── RDS Security Group ────────────────────────────────────────────────────────

resource "aws_security_group" "rds" {
  name        = "financial-vpc2-rds-sg"
  description = "RDS Security Group - Allow PostgreSQL from EKS nodes and VPC4 Headscale"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Allow PostgreSQL from EKS nodes"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.eks_node.id]
  }

  # eks_node SG는 vpc_config(컨트롤플레인 ENI)에만 부착되고, 워커 노드는
  # EKS 자동생성 cluster SG를 가지므로 파드→RDS 트래픽이 위 규칙으로는 막힘.
  # Temporal/MAS 파드의 RDS 접속 경로 확보를 위해 cluster SG도 허용.
  # (docs/TODO-temporal-rds-db.md — SG 갭 해결)
  ingress {
    description     = "Allow PostgreSQL from EKS pods (cluster security group)"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_eks_cluster.ops.vpc_config[0].cluster_security_group_id]
  }

  ingress {
    description = "Allow PostgreSQL from VPC4 Headscale (DB sync)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc4_cidr]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "financial-vpc2-rds-sg"
  }
}
