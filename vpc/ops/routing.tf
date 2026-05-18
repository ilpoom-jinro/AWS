# ──────────────────────────────────────────────────────────────────────────────
# VPC 2 — Private 라우팅 테이블
# IGW/NAT 없음 — VPC Endpoint 및 Peering 라우팅만
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "financial-vpc2-rt-private"
  }
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

# ──────────────────────────────────────────────────────────────────────────────
# VPC 2 — DB 라우팅 테이블
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_route_table" "db" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "financial-vpc2-rt-db"
  }
}

resource "aws_route_table_association" "db_a" {
  subnet_id      = aws_subnet.db_a.id
  route_table_id = aws_route_table.db.id
}

resource "aws_route_table_association" "db_b" {
  subnet_id      = aws_subnet.db_b.id
  route_table_id = aws_route_table.db.id
}
