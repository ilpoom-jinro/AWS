# ──────────────────────────────────────────────────────────────────────────────
# VPC 1 — Internet Gateway
# Public 서브넷(ALB) 인터넷 수신용
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "financial-vpc1-igw"
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# NAT Gateway용 Elastic IP
# Private 서브넷(EKS 노드)의 아웃바운드 인터넷 트래픽용
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "financial-vpc1-nat-eip"
  }

  depends_on = [aws_internet_gateway.this]
}

# ──────────────────────────────────────────────────────────────────────────────
# NAT Gateway
# AZ-a public 서브넷에 배치 (단일 NAT — 비용 절감)
# 고가용성이 필요하면 AZ-b에도 추가
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public_a.id

  tags = {
    Name = "financial-vpc1-nat"
  }

  depends_on = [aws_internet_gateway.this]
}
