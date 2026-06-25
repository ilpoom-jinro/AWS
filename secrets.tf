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
  kms_key_id              = data.aws_kms_key.key_secretsmanager.arn # aws/secretsmanager 기본키 대신 CMK 사용

  tags = {
    Name               = "financial-service-rds-password"
    DataClassification = "Restricted"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "service_rds_password" {
  secret_id = aws_secretsmanager_secret.service_rds_password.id
  secret_string = jsonencode({
    engine   = "postgres"
    username = "financial_admin"
    password = random_password.service_rds.result
    host     = module.vpc1.rds_address
    port     = 5432
    dbname   = "financial_service"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
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
  kms_key_id              = data.aws_kms_key.key_secretsmanager.arn # aws/secretsmanager 기본키 대신 CMK 사용

  tags = {
    Name               = "financial-ops-rds-password"
    DataClassification = "Restricted"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "ops_rds_password" {
  secret_id = aws_secretsmanager_secret.ops_rds_password.id
  secret_string = jsonencode({
    engine   = "postgres"
    username = "financial_admin"
    password = random_password.ops_rds.result
    host     = module.vpc2.rds_address
    port     = 5432
    dbname   = "financial_ops"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ── 자동 로테이션 ─────────────────────────────────────────────────────────────

# time_sleep: RDS·secret·SG경로가 다 준비된 뒤에도 available 직후 커넥션 거부 구간이
# 남아있어 회전 첫 발사 전에 버퍼를 둔다. (testSecret 12초 TCP 타임아웃 방지)
resource "time_sleep" "wait_for_service_rds" {
  depends_on = [
    module.vpc1,                                             # RDS 인스턴스 + Lambda→RDS SG 규칙 둘 다 커버
    aws_secretsmanager_secret_version.service_rds_password, # 루트 리소스 — 모듈에 안 덮임. 초기 비번 write 후 발사
  ]
  create_duration = "120s" # available != 커넥션 수락. testSecret 12초 타임아웃 구간을 넘기는 버퍼
}

resource "aws_secretsmanager_secret_rotation" "service_rds" {
  depends_on = [time_sleep.wait_for_service_rds] # 첫 발사를 버퍼 뒤로

  secret_id           = aws_secretsmanager_secret.service_rds_password.id
  rotation_lambda_arn = module.vpc1.rotation_lambda_arn
  rotate_immediately  = false

  rotation_rules {
    automatically_after_days = 30
  }
}

resource "aws_secretsmanager_secret_rotation" "ops_rds" {
  secret_id           = aws_secretsmanager_secret.ops_rds_password.id
  rotation_lambda_arn = module.vpc2.rotation_lambda_arn
  rotate_immediately  = false

  rotation_rules {
    automatically_after_days = 30
  }
}

# ── Temporal 전용 DB 자격증명 (공용 Temporal — Ops RDS) ────────────────────────
# DB(temporal, temporal_visibility) 및 role(temporal_user)은 init Job(옵션 B)이 생성.
# 이 Secret이 temporal_user 비밀번호의 source of truth — init Job이 읽어 CREATE ROLE에 사용.
# 상세: docs/TODO-temporal-rds-db.md
resource "random_password" "temporal_user" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "temporal_rds" {
  name                    = "temporal/rds-credentials"
  description             = "Temporal PostgreSQL credentials (temporal_user) on financial-ops RDS"
  recovery_window_in_days = 7
  kms_key_id              = data.aws_kms_key.key_secretsmanager.arn # aws/secretsmanager 기본키 대신 CMK 사용

  tags = {
    Name               = "temporal-rds-credentials"
    DataClassification = "Restricted"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "temporal_rds" {
  secret_id = aws_secretsmanager_secret.temporal_rds.id
  secret_string = jsonencode({
    username           = "temporal_user"
    password           = random_password.temporal_user.result
    host               = module.vpc2.rds_address
    port               = "5432"
    database           = "temporal"
    visibilityDatabase = "temporal_visibility"
  })
}
