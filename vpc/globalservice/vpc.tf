resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "financial-vpc1-service"
    Role = "대국민 서비스망"
  }
}
