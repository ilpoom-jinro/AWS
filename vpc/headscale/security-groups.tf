# ──────────────────────────────────────────────────────────────────────────────
# VPC 4 — Security Groups
# ──────────────────────────────────────────────────────────────────────────────

# ── Tailscale Router EC2 Security Group ───────────────────────────────────────

resource "aws_security_group" "headscale_router" {
  name        = "financial-vpc4-headscale-router-sg"
  description = "Tailscale Router EC2 SG - Allow WireGuard UDP from GCP and outbound DB sync"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Allow Tailscale UDP from GCP fixed IP"
    from_port   = 41641
    to_port     = 41641
    protocol    = "udp"
    cidr_blocks = [var.gcp_fixed_ip]
  }

  egress {
    description = "Allow Tailscale UDP to GCP"
    from_port   = 41641
    to_port     = 41641
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

  # on-prem OTel → Thanos Receive (ADR-0001 갭 E)
  # MASQUERADE 후 src=VPC4 ENI IP로 나가는 패킷이 VPC2 NLB(19291)로 향함
  # 목적지를 10.20.0.0/16 전체로 제한 (NLB SG ingress 19291만 열려 있어 최소 권한 유지)
  egress {
    description = "Allow Thanos Receive push to VPC2 monitoring NLB"
    from_port   = 19291
    to_port     = 19291
    protocol    = "tcp"
    cidr_blocks = [var.vpc2_cidr]
  }

  tags = {
    Name = "financial-vpc4-headscale-router-sg"
  }
}
