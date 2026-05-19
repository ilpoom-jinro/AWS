# ──────────────────────────────────────────────────────────────────────────────
# VPC 4 — Internet Gateway
# Tailscale Router EC2의 공인 IP 통신용
# NAT GW 불필요 — EC2에 Elastic IP 직접 부여 (eip.tf에서 추가)
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "financial-vpc4-igw"
  }
}
