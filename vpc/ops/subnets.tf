resource "aws_subnet" "private_a" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.20.11.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = false

  tags = {
    Name                              = "financial-vpc2-private-a"
    Type                              = "private"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

resource "aws_subnet" "private_b" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.20.12.0/24"
  availability_zone       = "${var.aws_region}b"
  map_public_ip_on_launch = false

  tags = {
    Name                              = "financial-vpc2-private-b"
    Type                              = "private"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

resource "aws_subnet" "db_a" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.20.21.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = false

  tags = {
    Name = "financial-vpc2-db-a"
    Type = "db"
  }
}

resource "aws_subnet" "db_b" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.20.22.0/24"
  availability_zone       = "${var.aws_region}b"
  map_public_ip_on_launch = false

  tags = {
    Name = "financial-vpc2-db-b"
    Type = "db"
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# 모니터링 전용 서브넷 (단일 AZ)
# Grafana, Thanos, Loki, Alertmanager 전용 노드 그룹 배치
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_subnet" "monitor_a" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.20.31.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = false

  tags = {
    Name                              = "financial-vpc2-monitor-a"
    Type                              = "private"
    "kubernetes.io/role/internal-elb" = "1"
  }
}
