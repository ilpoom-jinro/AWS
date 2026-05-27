# ──────────────────────────────────────────────────────────────────────────────
# VPC Peering — 5쌍
# ──────────────────────────────────────────────────────────────────────────────

# ── 1. VPC1 ↔ VPC2 (서비스망 ↔ 운영망) ────────────────────────────────────────

resource "aws_vpc_peering_connection" "vpc1_vpc2" {
  vpc_id      = var.vpc1_id
  peer_vpc_id = var.vpc2_id
  auto_accept = true

  tags = {
    Name = "financial-peering-vpc1-vpc2"
  }
}

# VPC1 라우팅 → VPC2
resource "aws_route" "vpc1_to_vpc2_public" {
  route_table_id            = var.vpc1_public_rt_id
  destination_cidr_block    = var.vpc2_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc1_vpc2.id
}

resource "aws_route" "vpc1_to_vpc2_private" {
  route_table_id            = var.vpc1_private_rt_id
  destination_cidr_block    = var.vpc2_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc1_vpc2.id
}

resource "aws_route" "vpc1_to_vpc2_db" {
  route_table_id            = var.vpc1_db_rt_id
  destination_cidr_block    = var.vpc2_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc1_vpc2.id
}

# VPC2 라우팅 → VPC1
resource "aws_route" "vpc2_to_vpc1_private" {
  route_table_id            = var.vpc2_private_rt_id
  destination_cidr_block    = var.vpc1_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc1_vpc2.id
}

resource "aws_route" "vpc2_to_vpc1_db" {
  route_table_id            = var.vpc2_db_rt_id
  destination_cidr_block    = var.vpc1_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc1_vpc2.id
}

# ── 2. VPC1 ↔ VPC3 (서비스망 ↔ Teleport) ──────────────────────────────────────

resource "aws_vpc_peering_connection" "vpc1_vpc3" {
  vpc_id      = var.vpc1_id
  peer_vpc_id = var.vpc3_id
  auto_accept = true

  tags = {
    Name = "financial-peering-vpc1-vpc3"
  }
}

# VPC1 라우팅 → VPC3
resource "aws_route" "vpc1_to_vpc3_public" {
  route_table_id            = var.vpc1_public_rt_id
  destination_cidr_block    = var.vpc3_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc1_vpc3.id
}

resource "aws_route" "vpc1_to_vpc3_private" {
  route_table_id            = var.vpc1_private_rt_id
  destination_cidr_block    = var.vpc3_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc1_vpc3.id
}

# VPC3 라우팅 → VPC1
resource "aws_route" "vpc3_to_vpc1" {
  route_table_id            = var.vpc3_private_rt_id
  destination_cidr_block    = var.vpc1_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc1_vpc3.id
}

# ── 3. VPC2 ↔ VPC3 (운영망 ↔ Teleport) ────────────────────────────────────────

resource "aws_vpc_peering_connection" "vpc2_vpc3" {
  vpc_id      = var.vpc2_id
  peer_vpc_id = var.vpc3_id
  auto_accept = true

  tags = {
    Name = "financial-peering-vpc2-vpc3"
  }
}

# VPC2 라우팅 → VPC3
resource "aws_route" "vpc2_to_vpc3_private" {
  route_table_id            = var.vpc2_private_rt_id
  destination_cidr_block    = var.vpc3_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc2_vpc3.id
}

resource "aws_route" "vpc2_to_vpc3_db" {
  route_table_id            = var.vpc2_db_rt_id
  destination_cidr_block    = var.vpc3_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc2_vpc3.id
}

# VPC3 라우팅 → VPC2
resource "aws_route" "vpc3_to_vpc2" {
  route_table_id            = var.vpc3_private_rt_id
  destination_cidr_block    = var.vpc2_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc2_vpc3.id
}

# ── 4. VPC4 ↔ VPC1 (Headscale ↔ 서비스 RDS) ───────────────────────────────────

resource "aws_vpc_peering_connection" "vpc4_vpc1" {
  vpc_id      = var.vpc4_id
  peer_vpc_id = var.vpc1_id
  auto_accept = true

  tags = {
    Name = "financial-peering-vpc4-vpc1"
  }
}

# VPC4 라우팅 → VPC1
resource "aws_route" "vpc4_to_vpc1" {
  route_table_id            = var.vpc4_public_rt_id
  destination_cidr_block    = var.vpc1_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc4_vpc1.id
}

# VPC1 DB 라우팅 → VPC4 (RDS가 Headscale EC2와 통신)
resource "aws_route" "vpc1_db_to_vpc4" {
  route_table_id            = var.vpc1_db_rt_id
  destination_cidr_block    = var.vpc4_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc4_vpc1.id
}

# ── 5. VPC4 ↔ VPC2 (Headscale ↔ 운영 RDS) ─────────────────────────────────────

resource "aws_vpc_peering_connection" "vpc4_vpc2" {
  vpc_id      = var.vpc4_id
  peer_vpc_id = var.vpc2_id
  auto_accept = true

  tags = {
    Name = "financial-peering-vpc4-vpc2"
  }
}

# VPC4 라우팅 → VPC2
resource "aws_route" "vpc4_to_vpc2" {
  route_table_id            = var.vpc4_public_rt_id
  destination_cidr_block    = var.vpc2_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc4_vpc2.id
}

# VPC2 DB 라우팅 → VPC4
resource "aws_route" "vpc2_db_to_vpc4" {
  route_table_id            = var.vpc2_db_rt_id
  destination_cidr_block    = var.vpc4_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc4_vpc2.id
}

# ── DNS Resolution 설정 ────────────────────────────────────────────────────────
# VPC3에서 VPC2 내부 DNS 조회 가능하도록 설정
# EKS API 서버 등 VPC2 private DNS 접근 필요

resource "aws_vpc_peering_connection_options" "vpc2_vpc3_requester" {
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc2_vpc3.id

  requester {
    allow_remote_vpc_dns_resolution = true
  }
}

resource "aws_vpc_peering_connection_options" "vpc2_vpc3_accepter" {
  vpc_peering_connection_id = aws_vpc_peering_connection.vpc2_vpc3.id

  accepter {
    allow_remote_vpc_dns_resolution = true
  }
}
