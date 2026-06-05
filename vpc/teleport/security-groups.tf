# ──────────────────────────────────────────────────────────────────────────────
# VPC 3 — Security Groups
# ──────────────────────────────────────────────────────────────────────────────

# ── Teleport EC2 Security Group ───────────────────────────────────────────────

resource "aws_security_group" "teleport" {
  name        = "financial-vpc3-teleport-sg"
  description = "Teleport EC2 Security Group - Allow SSH proxy and Teleport web UI via SSM only"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Allow Teleport proxy from VPC 1 (service)"
    from_port   = 3022
    to_port     = 3025
    protocol    = "tcp"
    cidr_blocks = [var.vpc1_cidr]
  }

  ingress {
    description = "Allow Teleport proxy from VPC 2 (ops)"
    from_port   = 3022
    to_port     = 3025
    protocol    = "tcp"
    cidr_blocks = [var.vpc2_cidr]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "financial-vpc3-teleport-sg"
  }
}

resource "aws_security_group_rule" "teleport_client_https" {
  count = length(var.teleport_allowed_client_cidrs) > 0 ? 1 : 0

  type              = "ingress"
  description       = "Allow Teleport web UI from approved client CIDRs"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = var.teleport_allowed_client_cidrs
  security_group_id = aws_security_group.teleport.id
}

resource "aws_security_group_rule" "teleport_client_proxy" {
  count = length(var.teleport_allowed_client_cidrs) > 0 ? 1 : 0

  type              = "ingress"
  description       = "Allow Teleport proxy from approved client CIDRs"
  from_port         = 3022
  to_port           = 3025
  protocol          = "tcp"
  cidr_blocks       = var.teleport_allowed_client_cidrs
  security_group_id = aws_security_group.teleport.id
}
