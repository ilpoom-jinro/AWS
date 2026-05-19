# ──────────────────────────────────────────────────────────────────────────────
# VPC 4 — Elastic IP
# Tailscale Router EC2에 고정 공인 IP 부여
# OCI Headscale이 이 IP로 노드를 등록
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_eip" "headscale_router" {
  domain   = "vpc"
  instance = aws_instance.headscale_router.id

  tags = {
    Name = "financial-vpc4-headscale-router-eip"
  }

  depends_on = [aws_internet_gateway.this]
}
