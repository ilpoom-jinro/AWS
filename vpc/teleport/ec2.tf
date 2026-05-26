# ──────────────────────────────────────────────────────────────────────────────
# VPC 3 — Teleport EC2
# 공인 IP 없음 — SSM으로만 접근
# ──────────────────────────────────────────────────────────────────────────────

# Ubuntu 22.04 LTS 최신 AMI 자동 조회
data "aws_ami" "ubuntu_22_04" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# SSM용 IAM Instance Profile
resource "aws_iam_role" "teleport_ec2" {
  name = "financial-vpc3-teleport-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "teleport_ssm" {
  role       = aws_iam_role.teleport_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "teleport_ec2" {
  name = "financial-vpc3-teleport-ec2-profile"
  role = aws_iam_role.teleport_ec2.name
}

# Teleport EC2
resource "aws_instance" "teleport" {
  ami                    = data.aws_ami.ubuntu_22_04.id
  instance_type          = "t3.small"
  subnet_id              = aws_subnet.private_a.id
  vpc_security_group_ids = [aws_security_group.teleport.id]
  iam_instance_profile   = aws_iam_instance_profile.teleport_ec2.name

  # 공인 IP 없음 — SSM으로만 접근
  associate_public_ip_address = false

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  user_data = <<-EOF
    #!/bin/bash
    apt-get update -y
    apt-get install -y curl wget

    # Teleport 설치
    curl https://goteleport.com/static/install.sh | bash -s 15.0.0
  EOF

  tags = {
    Name = "financial-vpc3-teleport"
    Role = "Teleport Access Proxy"
  }
}
