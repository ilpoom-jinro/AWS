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
      "export DEBIAN_FRONTEND=noninteractive",
      "sudo apt-get update -y",
      "sudo add-apt-repository universe -y",
      "sudo apt-get update -y",
      "sudo apt-get install -y curl wget unzip nfs-common"
    ]
  }

  # ── 2. K3s 설치 ────────────────────────────────────────────────────────────
  provisioner "shell" {
    inline = [
      # K3s 설치 및 시작 (이미지 pull을 위해 실행 필요)
      "curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=${var.k3s_version} sh -",
      "sudo systemctl enable k3s",

      # K3s 준비 대기
      "until sudo k3s kubectl get nodes 2>/dev/null | grep -q Ready; do echo 'K3s 준비 대기중...'; sleep 5; done",
      "echo 'K3s 준비 완료'"
    ]
  }

  # ── K3s 내장 이미지 사전 pull ────────────────────────────────────────────────
  provisioner "shell" {
    inline = [
      "sudo k3s ctr images pull docker.io/rancher/mirrored-pause:3.6",
      "sudo k3s ctr images pull docker.io/rancher/mirrored-coredns-coredns:1.11.1",
      "sudo k3s ctr images pull docker.io/rancher/mirrored-metrics-server:v0.7.0",
      "sudo k3s ctr images pull docker.io/rancher/local-path-provisioner:v0.0.28",
      "sudo k3s ctr images pull docker.io/rancher/mirrored-library-traefik:2.10.7",
      "sudo k3s ctr images pull docker.io/rancher/klipper-lb:v0.4.9",
      "echo '모든 K3s 이미지 pull 완료'"
    ]
  }

  # ── K3s 중지 및 클러스터 상태 초기화 (EC2 시작 시 fresh 클러스터로 시작) ────
  provisioner "shell" {
    inline = [
      "sudo systemctl stop k3s",
      "sudo systemctl disable k3s",
      # 빌드 노드의 클러스터 상태 제거 (노드 등록 정보, etcd 등)
      # 이미지 캐시(/var/lib/rancher/k3s/agent/containerd)는 유지
      "sudo rm -rf /var/lib/rancher/k3s/server",
      "sudo rm -rf /var/lib/rancher/k3s/agent/client-*.crt",
      "sudo rm -rf /var/lib/rancher/k3s/agent/client-*.key",
      "sudo rm -rf /var/lib/rancher/k3s/agent/node-name.conf",
      "sudo rm -rf /etc/rancher/k3s/k3s.yaml"
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

  # ── aws-iam-authenticator 설치 ──────────────────────────────────────────────
  provisioner "shell" {
    inline = [
      "sudo curl -L -o /usr/local/bin/aws-iam-authenticator https://github.com/kubernetes-sigs/aws-iam-authenticator/releases/download/v0.6.14/aws-iam-authenticator_0.6.14_linux_amd64",
      "sudo chmod +x /usr/local/bin/aws-iam-authenticator",
      "aws-iam-authenticator version"
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
