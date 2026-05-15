resource "aws_vpc" "vpc4_headscale" {
  cidr_block           = var.vpc4_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Elastic IP 부여 예정 (3단계 igw.tf에서 추가)
  # GCP와 WireGuard P2P 터미네이션 포인트

  tags = {
    Name = "financial-vpc4-headscale"
    Role = "Headscale Router (WireGuard)"
  }
}
