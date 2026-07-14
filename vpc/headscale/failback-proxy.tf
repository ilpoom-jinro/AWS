# AWS RDS는 Cloud SQL PSA 대역으로 직접 route를 갖지 않습니다.
# 따라서 VPC4 Headscale Router의 내부 전용 TCP proxy를 경유해 Cloud SQL publisher에 연결합니다.
locals {
  cloudsql_failback_proxy_enabled = trimspace(var.gcp_cloudsql_private_ip) != ""
}

resource "aws_ssm_association" "cloudsql_failback_proxy" {
  count = local.cloudsql_failback_proxy_enabled ? 1 : 0

  name             = "AWS-RunShellScript"
  association_name = "financial-vpc4-cloudsql-failback-proxy"

  targets {
    key    = "InstanceIds"
    values = [aws_instance.headscale_router.id]
  }

  parameters = {
    commands = <<-EOT
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y socat

      cat >/etc/systemd/system/cloudsql-failback-proxy.service <<'UNIT'
      [Unit]
      Description=Cloud SQL failback TCP proxy
      After=network-online.target tailscaled.service
      Wants=network-online.target

      [Service]
      Type=simple
      ExecStart=/usr/bin/socat TCP-LISTEN:${var.cloudsql_failback_proxy_port},fork,reuseaddr,keepalive TCP:${var.gcp_cloudsql_private_ip}:5432
      Restart=always
      RestartSec=5

      [Install]
      WantedBy=multi-user.target
      UNIT

      systemctl daemon-reload
      systemctl enable --now cloudsql-failback-proxy.service
    EOT
  }
}
