resource "aws_vpc" "vpc2_ops" {
  cidr_block           = var.vpc2_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  # IGW / NAT GW 없음 — VPC Endpoint로만 AWS API 접근
  # enable_dns_hostnames = true 는 VPC Endpoint Private DNS 필수 조건

  tags = {
    Name = "financial-vpc2-ops"
    Role = "내부 운영망 (완전 격리)"
  }
}
