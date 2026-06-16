# =============================================
# RDS 마스터 비밀번호 — Secrets Manager
# vpc 모듈 destroy 시 prevent_destroy 충돌 방지를 위해 루트 레벨로 분리
# =============================================

# ── Service RDS (VPC1) ────────────────────────────────────────────────────────

resource "random_password" "service_rds" {
  length  = 32
  special = false
}

resource "random_password" "teleport_app_join_token" {
  length  = 48
  special = false
}

# ── 내부 Git(Gitea) 관리자 비밀번호 ────────────────────────────────────────────

resource "random_password" "internal_git_admin" {
  length  = 24
  special = false
}

resource "aws_secretsmanager_secret" "service_rds_password" {
  name                    = "financial-service-rds-password"
  description             = "RDS master password for financial-service PostgreSQL"
  recovery_window_in_days = 7

  tags = {
    Name = "financial-service-rds-password"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "service_rds_password" {
  secret_id = aws_secretsmanager_secret.service_rds_password.id
  secret_string = jsonencode({
    username = "financial_admin"
    password = random_password.service_rds.result
  })
}

# ── Ops RDS (VPC2) ────────────────────────────────────────────────────────────

resource "random_password" "ops_rds" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "ops_rds_password" {
  name                    = "financial-ops-rds-password"
  description             = "RDS master password for financial-ops PostgreSQL"
  recovery_window_in_days = 7

  tags = {
    Name = "financial-ops-rds-password"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "ops_rds_password" {
  secret_id = aws_secretsmanager_secret.ops_rds_password.id
  secret_string = jsonencode({
    username = "financial_admin"
    password = random_password.ops_rds.result
  })
}

# ── ArgoCD 로컬 계정 비밀번호 ──────────────────────────────────────────────────
# 값은 코드에 없음 — destroy/apply 사이클 생존을 위해 prevent_destroy = true
# 최초 1회: aws secretsmanager put-secret-value --secret-id argocd/local-account-passwords \
#   --secret-string '{"dahyeon":"...","bgshin":"...","junho":"...","sangjun":"...","junyounglee":"..."}'

resource "aws_secretsmanager_secret" "argocd_local_account_passwords" {
  name                    = "argocd/local-account-passwords"
  description             = "ArgoCD local account passwords (JSON) — populate manually via AWS CLI; never store values in code"
  recovery_window_in_days = 7

  lifecycle {
    prevent_destroy = true
  }
}
