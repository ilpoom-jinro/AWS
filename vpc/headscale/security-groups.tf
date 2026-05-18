# ──────────────────────────────────────────────────────────────────────────────
# VPC 4 — Security Groups
# ──────────────────────────────────────────────────────────────────────────────

# ── Tailscale Router EC2 Security Group ───────────────────────────────────────

resource "aws_security_group" "headscale_router" {
  name        = "financial-vpc4-headscale-router-sg"
  description = "Tailscale Router EC2 SG - Allow WireGuard UDP from GCP and outbound DB sync"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Allow WireGuard UDP from GCP fixed IP"
    from_port   = 51820
    to_port     = 51820
    protocol    = "udp"
    cidr_blocks = [var.gcp_fixed_ip]
  }

  egress {
    description = "Allow WireGuard UDP to GCP"
    from_port   = 51820
    to_port     = 51820
    protocol    = "udp"
    cidr_blocks = [var.gcp_fixed_ip]
  }

  egress {
    description = "Allow PostgreSQL to VPC1 RDS (DB sync)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc1_cidr]
  }

  egress {
    description = "Allow PostgreSQL to VPC2 RDS (DB sync)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc2_cidr]
  }

  egress {
    description = "Allow HTTPS to OCI Headscale (control plane)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.oci_headscale_ip]
  }

  egress {
    description = "Allow HTTPS for SSM Session Manager"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "financial-vpc4-headscale-router-sg"
  }
}
