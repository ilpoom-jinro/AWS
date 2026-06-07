# ──────────────────────────────────────────────────────────────────────────────
# VPC 3 — Teleport EC2
# Packer AMI 사용 (K3s + Teleport v17 포함)
# 공인 IP 없음 — SSM으로만 접근
# ──────────────────────────────────────────────────────────────────────────────

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

# ECR pull 권한 (K3s가 ECR에서 Teleport 이미지 pull)
resource "aws_iam_role_policy_attachment" "teleport_ecr" {
  role       = aws_iam_role.teleport_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy" "teleport_eks" {
  name = "teleport-eks-describe"
  role = aws_iam_role.teleport_ec2.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["eks:DescribeCluster"]
      Resource = "arn:aws:eks:ap-northeast-2:${data.aws_caller_identity.current.account_id}:cluster/financial-ops-eks"
    }]
  })
}

resource "aws_iam_instance_profile" "teleport_ec2" {
  name = "financial-vpc3-teleport-ec2-profile"
  role = aws_iam_role.teleport_ec2.name
}

# Teleport EC2 (Packer AMI)
resource "aws_instance" "teleport" {
  ami                         = var.teleport_ami_id
  instance_type               = "t3.small"
  subnet_id                   = aws_subnet.private_a.id
  vpc_security_group_ids      = [aws_security_group.teleport.id]
  iam_instance_profile        = aws_iam_instance_profile.teleport_ec2.name
  associate_public_ip_address = false

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  user_data = base64encode(templatefile("${path.module}/userdata.sh.tpl", {
    eks_endpoint = var.eks_endpoint
    eks_ca_data  = var.eks_ca_data
    efs_dns      = "${aws_efs_file_system.teleport.id}.efs.${var.aws_region}.amazonaws.com"
  }))

  depends_on = [aws_efs_mount_target.teleport_a]

  tags = {
    Name = "financial-vpc3-teleport"
    Role = "Teleport Access Proxy"
  }
}
