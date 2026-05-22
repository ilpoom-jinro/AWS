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
