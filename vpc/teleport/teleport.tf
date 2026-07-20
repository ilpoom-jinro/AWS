data "aws_caller_identity" "current" {}

data "aws_ami" "teleport" {
  # destroy 시 teleport_ami_id_override가 주어지면 이 조회를 건너뛴다.
  # Packer AMI가 이미 사라진 상태에서는 조회 자체가 실패해 plan이 막히기 때문.
  count       = var.teleport_ami_id_override == null ? 1 : 0
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
