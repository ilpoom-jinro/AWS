# ──────────────────────────────────────────────────────────────────────────────
# VPC 3 — VPC Endpoints
#
# Teleport EC2 SSM 관리를 위한 Endpoint 구성
# IGW/NAT 없는 환경에서 AWS SSM 접근을 위해 필요
# 인터넷 경유 없음 → 금융권 망분리 요건 충족
# ──────────────────────────────────────────────────────────────────────────────

# ── Endpoint 전용 Security Group ──────────────────────────────────────────────

resource "aws_security_group" "endpoints" {
  name        = "financial-vpc3-endpoint-sg"
  description = "Security Group for VPC Endpoints - Allow HTTPS from within VPC 3"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Allow HTTPS from within VPC 3"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "financial-vpc3-endpoint-sg"
  }
}

# ── SSM Interface Endpoints ────────────────────────────────────────────────────
# Teleport EC2 SSM 접속에 필요한 3개 Endpoint

resource "aws_vpc_endpoint" "ssm" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id]
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc3-endpoint-ssm"
  }
}

resource "aws_vpc_endpoint" "ssmmessages" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id]
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc3-endpoint-ssmmessages"
  }
}

resource "aws_vpc_endpoint" "ec2messages" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ec2messages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id]
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc3-endpoint-ec2messages"
  }
}
