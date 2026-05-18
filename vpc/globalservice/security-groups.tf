# ──────────────────────────────────────────────────────────────────────────────
# VPC 1 — Security Groups
# ──────────────────────────────────────────────────────────────────────────────

# ── ALB Security Group ────────────────────────────────────────────────────────

resource "aws_security_group" "alb" {
  name        = "financial-vpc1-alb-sg"
  description = "ALB Security Group - Allow inbound HTTP/HTTPS from internet"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Allow HTTP from internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Allow HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "financial-vpc1-alb-sg"
  }
}

# ── EKS Node Security Group ───────────────────────────────────────────────────

resource "aws_security_group" "eks_node" {
  name        = "financial-vpc1-eks-node-sg"
  description = "EKS Node Security Group - Allow traffic from ALB and within node group"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Allow traffic from ALB"
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description = "Allow inter-node communication"
    from_port   = 0
    to_port     = 65535
    protocol    = "-1"
    self        = true
  }

  ingress {
    description = "Allow inbound from VPC 2 ops (Peering)"
    from_port   = 0
    to_port     = 65535
    protocol    = "-1"
    cidr_blocks = [var.vpc2_cidr]
  }

  ingress {
    description = "Allow inbound from VPC 3 Teleport (Peering)"
    from_port   = 0
    to_port     = 65535
    protocol    = "-1"
    cidr_blocks = [var.vpc3_cidr]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "financial-vpc1-eks-node-sg"
  }
}

# ── RDS Security Group ────────────────────────────────────────────────────────

resource "aws_security_group" "rds" {
  name        = "financial-vpc1-rds-sg"
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
    Name = "financial-vpc1-rds-sg"
  }
}
