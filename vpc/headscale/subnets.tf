resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.40.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true

  # OCI Headscale이 이 EC2를 찾아 등록할 수 있도록 공인 IP 필요

  tags = {
    Name = "financial-vpc4-public-a"
    Type = "public"
  }
}
