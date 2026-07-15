# AWS RDS는 Cloud SQL PSA 대역으로 직접 route를 갖지 않습니다.
# 따라서 VPC4 Headscale Router의 내부 전용 TCP proxy를 경유해 Cloud SQL publisher에 연결합니다.
locals {
  cloudsql_failback_proxy_enabled     = trimspace(var.gcp_cloudsql_private_ip) != ""
  cloudsql_reverse_replication_script = base64encode(file("${path.module}/files/cloudsql-reverse-replication"))
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
      set -eu
      export DEBIAN_FRONTEND=noninteractive

      # Router SG는 패키지 저장소에 HTTPS(443)만 허용한다. Ubuntu 기본 HTTP source를
      # HTTPS로 전환해 최소권한 egress 정책을 유지한다.
      find /etc/apt -type f \( -name '*.list' -o -name '*.sources' \) -print | while IFS= read -r source_file; do
        sed -i 's|http://|https://|g' "$${source_file}"
      done

      apt-get update -y
      apt-get install -y ca-certificates curl gnupg socat

      install -d -m 0755 /etc/apt/keyrings
      curl --fail --silent --show-error https://www.postgresql.org/media/keys/ACCC4CF8.asc | \
        gpg --dearmor --yes -o /etc/apt/keyrings/postgresql.gpg
      . /etc/os-release
      echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt $${VERSION_CODENAME}-pgdg main" \
        >/etc/apt/sources.list.d/pgdg.list

      apt-get update -y
      apt-get install -y postgresql-client-16

      install -d -m 0755 /usr/local/sbin
      echo '${local.cloudsql_reverse_replication_script}' | base64 --decode >/usr/local/sbin/cloudsql-reverse-replication
      chmod 0700 /usr/local/sbin/cloudsql-reverse-replication

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
