packer {
  required_plugins {
    amazon = {
      version = ">= 1.2.8"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# Variables
# ──────────────────────────────────────────────────────────────────────────────

variable "aws_region" {
  type    = string
  default = "ap-northeast-2"
}

variable "teleport_version" {
  type    = string
  default = "17.0.0"
}

variable "k3s_version" {
  type    = string
  default = "v1.31.0+k3s1"
}

variable "vpc_id" {
  type        = string
  description = "Packer 빌드용 VPC ID (임시 EC2 생성 위치)"
}

variable "subnet_id" {
  type        = string
  description = "Packer 빌드용 Subnet ID (Public 서브넷 필요)"
}

# ──────────────────────────────────────────────────────────────────────────────
# Source — Ubuntu 22.04 LTS 기반
# ──────────────────────────────────────────────────────────────────────────────

source "amazon-ebs" "teleport_k3s" {
  region        = var.aws_region
  instance_type = "t3.small"

  # Ubuntu 22.04 LTS 최신 AMI 자동 조회
  source_ami_filter {
    filters = {
      name                = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["099720109477"] # Canonical
  }

  ssh_username = "ubuntu"

  # 빌드용 임시 EC2 설정
  vpc_id    = var.vpc_id
  subnet_id = var.subnet_id

  # 빌드 완료 후 AMI 이름
  ami_name        = "financial-teleport-k3s-${var.teleport_version}-{{timestamp}}"
  ami_description = "Teleport v${var.teleport_version} + K3s ${var.k3s_version} on Ubuntu 22.04"

  tags = {
    Name            = "financial-teleport-k3s"
    TeleportVersion = var.teleport_version
    K3sVersion      = var.k3s_version
    BaseOS          = "Ubuntu-22.04"
    ManagedBy       = "Packer"
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# Build
# ──────────────────────────────────────────────────────────────────────────────

build {
  name    = "teleport-k3s"
  sources = ["source.amazon-ebs.teleport_k3s"]

  # ── 1. 시스템 업데이트 ──────────────────────────────────────────────────────
  provisioner "shell" {
    inline = [
      "sudo apt-get update -y",
      "sudo apt-get install -y curl wget unzip"
    ]
  }

  # ── 2. K3s 설치 ────────────────────────────────────────────────────────────
  provisioner "shell" {
    inline = [
      # K3s 바이너리 다운로드 (인터넷 가능한 빌드 환경에서)
      "curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=${var.k3s_version} INSTALL_K3S_SKIP_ENABLE=true sh -",

      # K3s 자동 시작 비활성화 (EC2 시작 시 user_data에서 설정 후 시작)
      "sudo systemctl disable k3s || true"
    ]
  }

  # ── 3. K3s ECR 레지스트리 설정 ──────────────────────────────────────────────
  provisioner "shell" {
    inline = [
      "sudo mkdir -p /etc/rancher/k3s",
    ]
  }

  provisioner "file" {
    content = <<-EOF
      mirrors:
        "218549830271.dkr.ecr.ap-northeast-2.amazonaws.com":
          endpoint:
            - "https://218549830271.dkr.ecr.ap-northeast-2.amazonaws.com"
      configs:
        "218549830271.dkr.ecr.ap-northeast-2.amazonaws.com":
          auth:
            username: "AWS"
    EOF
    destination = "/tmp/registries.yaml"
  }

  provisioner "shell" {
    inline = [
      "sudo mv /tmp/registries.yaml /etc/rancher/k3s/registries.yaml",
      "sudo chmod 600 /etc/rancher/k3s/registries.yaml"
    ]
  }

  # ── 4. Teleport 설치 ────────────────────────────────────────────────────────
  provisioner "shell" {
    inline = [
      # Teleport apt 저장소 추가
      "curl https://apt.releases.teleport.dev/gpg -o /tmp/teleport.gpg",
      "sudo install -o root -g root -m 644 /tmp/teleport.gpg /usr/share/keyrings/teleport-archive-keyring.asc",
      "echo 'deb [signed-by=/usr/share/keyrings/teleport-archive-keyring.asc] https://apt.releases.teleport.dev/ubuntu jammy stable/v17' | sudo tee /etc/apt/sources.list.d/teleport.list",
      "sudo apt-get update -y",
      "sudo apt-get install -y teleport",

      # Teleport 자동 시작 비활성화 (user_data에서 설정 후 시작)
      "sudo systemctl disable teleport || true"
    ]
  }

  # ── 5. IP Forwarding 사전 설정 ──────────────────────────────────────────────
  provisioner "shell" {
    inline = [
      "echo 'net.ipv4.ip_forward = 1' | sudo tee /etc/sysctl.d/99-teleport.conf",
      "echo 'net.ipv6.conf.all.forwarding = 1' | sudo tee -a /etc/sysctl.d/99-teleport.conf"
    ]
  }

  # ── 6. AMI 정리 ─────────────────────────────────────────────────────────────
  provisioner "shell" {
    inline = [
      "sudo apt-get clean || true",
      "sudo rm -rf /var/lib/apt/lists/* || true",
      "sudo find /tmp -maxdepth 1 -type f -delete || true"
    ]
  }

  # ── 빌드 완료 메시지 ────────────────────────────────────────────────────────
  post-processor "manifest" {
    output     = "manifest.json"
    strip_path = true
  }
}
