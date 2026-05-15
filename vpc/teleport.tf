resource "aws_vpc" "vpc3_teleport" {
  cidr_block           = var.vpc3_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  # 공인 IP 없음 — 개발자 접근은 SSM → Teleport 경로만 허용

  tags = {
    Name = "financial-vpc3-teleport"
    Role = "Teleport 접근망"
  }
}
