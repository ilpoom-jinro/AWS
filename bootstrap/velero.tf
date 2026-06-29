# ──────────────────────────────────────────────────────────────────────────────
# #17 Velero 백업 — 지속 레이어 (bootstrap state, destroy 주기 밖)
#
# terraform destroy/apply를 반복해도 기존 백업을 복원할 수 있으려면
# 백업 데이터(S3)와 복호화 키(Kopia 암호)가 살아 있어야 함.
# KMS(kms/), Terraform state(bootstrap/main.tf)와 동일 패턴으로 bootstrap state에 배치.
# ──────────────────────────────────────────────────────────────────────────────

data "aws_kms_alias" "key_secretsmanager" {
  name = "alias/key-secretsmanager"
}

# ── Kopia repository 암호 ──────────────────────────────────────────────────────
# 클러스터 재생성 후에도 기존 S3 저장소를 복호화할 수 있게 암호를 안정적으로 유지.
# ignore_changes = all: 최초 생성 후 apply마다 재생성·회전되지 않게 값 고정.

resource "random_password" "kopia_repo" {
  length  = 32
  special = false # 셸 주입 위험 문자 회피

  lifecycle {
    ignore_changes = all # 값이 바뀌면 기존 백업 복호화 불가 — 절대 변경 금지
  }
}

resource "aws_secretsmanager_secret" "kopia_repo_password" {
  name                    = "velero/kopia-repo-password"
  description             = "Kopia repository encryption password — Velero node-agent가 S3 백업 저장소 암·복호화에 사용"
  kms_key_id              = data.aws_kms_alias.key_secretsmanager.target_key_arn
  recovery_window_in_days = 0 # destroy 즉시 삭제 — re-apply 시 동일 이름으로 재생성됨

  tags = {
    Name = "velero-kopia-repo-password"
  }
}

resource "aws_secretsmanager_secret_version" "kopia_repo_password" {
  secret_id = aws_secretsmanager_secret.kopia_repo_password.id
  secret_string = jsonencode({
    repository-password = random_password.kopia_repo.result
  })

  lifecycle {
    ignore_changes = [secret_string] # 최초 생성 후 값 고정 — 재apply로 암호 바뀌면 기존 백업 복호화 불가
  }
}

# ── Velero 백업 S3 버킷 ────────────────────────────────────────────────────────

resource "aws_s3_bucket" "velero_backup" {
  bucket        = "financial-velero-backup-${data.aws_caller_identity.current.account_id}"
  force_destroy = false # 백업 데이터 실수 삭제 방지

  tags = {
    Name               = "financial-velero-backup"
    DataClassification = "Confidential"
  }
}

resource "aws_s3_bucket_versioning" "velero_backup" {
  bucket = aws_s3_bucket.velero_backup.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "velero_backup" {
  bucket = aws_s3_bucket.velero_backup.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = data.aws_kms_alias.key_s3.target_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "velero_backup" {
  bucket                  = aws_s3_bucket.velero_backup.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "velero_backup" {
  bucket = aws_s3_bucket.velero_backup.id

  rule {
    id     = "velero-backup-expiry"
    status = "Enabled"
    filter { prefix = "" }

    # Velero Schedule TTL=14일(336h)이 오브젝트를 만료 처리하지만
    # 미완료 멀티파트 업로드·noncurrent version 누적 방지용 안전망.
    abort_incomplete_multipart_upload {
      days_after_initiation = 2
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }

    expiration {
      days = 30 # Velero TTL(14일) 이후 미정리 오브젝트 안전망
    }
  }

  depends_on = [aws_s3_bucket_versioning.velero_backup]
}
