resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Tailscale Router EC2 + Elastic IP 부여 예정
  # GCP와 WireGuard P2P 터미네이션 포인트

  tags = {
    Name = "financial-vpc4-headscale"
    Role = "Headscale Router (WireGuard)"
  }
}
