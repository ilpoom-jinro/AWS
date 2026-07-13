# ──────────────────────────────────────────────────────────────────────────────
# VPC 4 — Tailscale Router EC2
# OCI Headscale Control Plane에 등록
# GCP와 WireGuard P2P 터미네이션
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
resource "aws_iam_role" "headscale_router_ec2" {
  name = "financial-vpc4-headscale-router-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "headscale_router_ssm" {
  role       = aws_iam_role.headscale_router_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "headscale_router_ec2" {
  name = "financial-vpc4-headscale-router-ec2-profile"
  role = aws_iam_role.headscale_router_ec2.name
}

# Tailscale Router EC2
resource "aws_instance" "headscale_router" {
  ami                    = data.aws_ami.ubuntu_22_04.id
  instance_type          = "t3.small"
  subnet_id              = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.headscale_router.id]
  iam_instance_profile   = aws_iam_instance_profile.headscale_router_ec2.name

  associate_public_ip_address = true

  # IP 포워딩 활성화 (Subnet Router 필수)
  source_dest_check = false

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  user_data = <<-EOF
    #!/bin/bash
    # OS 레벨 IP 포워딩 활성화
    echo 'net.ipv4.ip_forward = 1' | tee -a /etc/sysctl.d/99-custom.conf
    sysctl -p /etc/sysctl.d/99-custom.conf

    # Tailscale 설치
    curl -fsSL https://tailscale.com/install.sh | sh

    # SNAT 설정 (GKE Pod → AWS 통신 시 라우터 IP로 위장)
    iptables -t nat -A POSTROUTING -o tailscale0 -j MASQUERADE
    # on-prem → VPC 서브넷 라우팅: Tailscale CGNAT src → 기본 NIC IP로 SNAT (ADR-0001 갭 C)
    # 이 규칙 없으면 VPC2 NLB가 100.x.x.x src를 받아도 return route가 없어 TCP 연결 실패
    PRIMARY_INTERFACE=$(ip route show default | awk '/default/ {print $5; exit}')
    iptables -t nat -A POSTROUTING -s 100.64.0.0/10 -o "$${PRIMARY_INTERFACE}" -j MASQUERADE

    # MTU 문제 방지 TCP MSS 조정
    iptables -t mangle -A FORWARD -o tailscale0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

    # iptables 재부팅 후 유지
    apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
    netfilter-persistent save

    # Tailscale 실행 (OCI Headscale 등록)
    # --advertise-routes: AWS VPC 대역을 Tailscale 네트워크에 광고
    # --snat-subnet-routes=false: iptables SNAT 사용
    tailscale up \
      --login-server ${var.headscale_login_server} \
      --authkey ${var.tailscale_auth_key} \
      --advertise-routes=10.10.0.0/16,10.20.0.0/16 \
      --snat-subnet-routes=false
  EOF

  tags = {
    Name = "financial-vpc4-headscale-router"
    Role = "Tailscale Subnet Router"
  }
}
