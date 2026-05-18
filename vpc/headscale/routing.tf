# ──────────────────────────────────────────────────────────────────────────────
# VPC 4 — Public 라우팅 테이블
# 목적지 0.0.0.0/0 → IGW
# OCI Headscale 등록 및 WireGuard P2P 통신용
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "financial-vpc4-rt-public"
  }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}
