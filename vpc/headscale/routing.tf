# ──────────────────────────────────────────────────────────────────────────────
# VPC 4 — Public 라우팅 테이블
# 목적지 0.0.0.0/0 → IGW
# OCI Headscale 등록 및 WireGuard P2P 통신용
#
# 인라인 route 블록을 사용하지 않는 이유:
# peering.tf에서 aws_route 리소스로 VPC1/VPC2 peering route를 추가하는데,
# 인라인 route와 aws_route를 혼용하면 apply마다 서로 덮어쓰는 drift가 발생함.
# 모든 route를 aws_route 리소스로 통일하여 충돌 방지.
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "financial-vpc4-rt-public"
  }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}
