data "aws_caller_identity" "current" {}

data "aws_ami" "teleport" {
  most_recent = true
  owners      = ["self"]

  filter {
    name   = "tag:Name"
    values = ["financial-teleport-k3s"]
  }

  filter {
    name   = "tag:ManagedBy"
    values = ["Packer"]
  }
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  # 공인 IP 없음 — 개발자 접근은 SSM → Teleport 경로만 허용

  tags = {
    Name = "financial-vpc3-teleport"
    Role = "Teleport 접근망"
  }
}
