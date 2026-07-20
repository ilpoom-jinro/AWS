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
      apt-get install -y awscli ca-certificates curl gnupg jq socat

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

# 시크릿 자체(aws_secretsmanager_secret)는 루트 secrets.tf에서 관리한다.
# prevent_destroy가 destroy 사이클용 모듈(vpc/headscale) 안에 있으면 vpc4
# destroy 자체를 막기 때문 — ARN은 var.cloudsql_failback_credentials_secret_arn으로 전달받는다.
resource "aws_iam_role_policy" "headscale_router_failback_credentials" {
  name = "financial-vpc4-cloudsql-failback-credentials-read"
  role = aws_iam_role.headscale_router_ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadFailbackCredentialsOnly"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          var.cloudsql_failback_credentials_secret_arn,
          var.service_rds_secret_arn
        ]
      },
      {
        Sid      = "DecryptServiceRdsCredentials"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:DescribeKey"]
        Resource = var.service_rds_kms_key_arn
      }
    ]
  })
}

resource "aws_ssm_document" "cloudsql_reverse_replication" {
  name            = "financial-vpc4-cloudsql-reverse-replication"
  document_type   = "Command"
  document_format = "JSON"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Run controlled Cloud SQL to AWS RDS reverse replication on the VPC4 Router"
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "runCloudSqlReverseReplication"
      inputs = {
        runCommand = [<<-EOT
          #!/usr/bin/env bash
          set -euo pipefail

          export AWS_REGION='${var.aws_region}'
          export AWS_DEFAULT_REGION='${var.aws_region}'

          command -v aws >/dev/null
          command -v jq >/dev/null
          test -x /usr/local/sbin/cloudsql-reverse-replication

          failback_secret="$(aws secretsmanager get-secret-value \
            --secret-id '${var.cloudsql_failback_credentials_secret_arn}' \
            --query SecretString --output text)"
          rds_secret="$(aws secretsmanager get-secret-value \
            --secret-id '${var.service_rds_secret_arn}' \
            --query SecretString --output text)"

          export CLOUDSQL_ADMIN_USER="$(jq -er '.cloudsql_admin_user' <<<"$${failback_secret}")"
          export CLOUDSQL_ADMIN_PASSWORD="$(jq -er '.cloudsql_admin_password' <<<"$${failback_secret}")"
          export REPLICATION_PASSWORD="$(jq -er '.replication_password' <<<"$${failback_secret}")"
          export RDS_HOST="$(jq -er '.host' <<<"$${rds_secret}")"
          export RDS_ADMIN_USER="$(jq -er '.username' <<<"$${rds_secret}")"
          export RDS_ADMIN_PASSWORD="$(jq -er '.password' <<<"$${rds_secret}")"
          export FAILBACK_PROXY_HOST='${aws_instance.headscale_router.private_ip}'

          exec /usr/local/sbin/cloudsql-reverse-replication \
            --execute \
            --gcp-writes-fenced \
            --rebuild-rds-from-cloudsql \
            --terminate-rds-sessions \
            --confirm CREATE_REVERSE_REPLICATION
        EOT
        ]
      }
    }]
  })
}

# 다음 AWS -> GCP DMS 주기를 만들기 전에 failback용 native logical replication
# 객체만 제거합니다. Cloud SQL 인스턴스나 RDS 데이터는 삭제하지 않습니다.
resource "aws_ssm_document" "cloudsql_reverse_replication_cleanup" {
  name            = "financial-vpc4-cloudsql-reverse-replication-cleanup"
  document_type   = "Command"
  document_format = "JSON"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Remove controlled Cloud SQL to AWS RDS reverse replication before DMS rearm"
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "cleanupCloudSqlReverseReplication"
      inputs = {
        runCommand = [<<-EOT
          #!/usr/bin/env bash
          set -euo pipefail

          export AWS_REGION='${var.aws_region}'
          export AWS_DEFAULT_REGION='${var.aws_region}'

          command -v aws >/dev/null
          command -v jq >/dev/null
          test -x /usr/local/sbin/cloudsql-reverse-replication

          failback_secret="$(aws secretsmanager get-secret-value \
            --secret-id '${var.cloudsql_failback_credentials_secret_arn}' \
            --query SecretString --output text)"
          rds_secret="$(aws secretsmanager get-secret-value \
            --secret-id '${var.service_rds_secret_arn}' \
            --query SecretString --output text)"

          export CLOUDSQL_ADMIN_USER="$(jq -er '.cloudsql_admin_user' <<<"$${failback_secret}")"
          export CLOUDSQL_ADMIN_PASSWORD="$(jq -er '.cloudsql_admin_password' <<<"$${failback_secret}")"
          export REPLICATION_PASSWORD="$(jq -er '.replication_password' <<<"$${failback_secret}")"
          export RDS_HOST="$(jq -er '.host' <<<"$${rds_secret}")"
          export RDS_ADMIN_USER="$(jq -er '.username' <<<"$${rds_secret}")"
          export RDS_ADMIN_PASSWORD="$(jq -er '.password' <<<"$${rds_secret}")"
          export FAILBACK_PROXY_HOST='${aws_instance.headscale_router.private_ip}'

          exec /usr/local/sbin/cloudsql-reverse-replication \
            --cleanup \
            --gcp-writes-fenced \
            --confirm REMOVE_REVERSE_REPLICATION
        EOT
        ]
      }
    }]
  })
}
