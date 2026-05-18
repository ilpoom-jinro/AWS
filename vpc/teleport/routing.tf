# ──────────────────────────────────────────────────────────────────────────────
# VPC 3 — Private 라우팅 테이블
# SSM, Peering 라우팅만 — IGW/NAT 없음
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "financial-vpc3-rt-private"
  }
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}
