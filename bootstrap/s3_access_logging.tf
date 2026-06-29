# =============================================
# #18 API 호출 추적 — S3 Server Access Logging (bootstrap 버킷 4개)
#
# target 버킷(financial-s3-access-logs-{account_id})은
# security 모듈(security/s3_access_logging.tf)에서 생성.
#
# ⚠️ apply 순서: root workspace → bootstrap workspace
#   data source가 plan 시 버킷 존재를 검증 —
#   security 모듈 먼저 apply 안 하면 terraform plan 자체가 실패함 (조용한 실패 방지).
# =============================================

# target 버킷 존재 여부를 plan-time에 검증
data "aws_s3_bucket" "s3_access_logs" {
  bucket = "financial-s3-access-logs-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_logging" "cloudtrail_logs_locked" {
  bucket        = aws_s3_bucket.cloudtrail_logs_locked.id
  target_bucket = data.aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/cloudtrail-logs/"
}

resource "aws_s3_bucket_logging" "terraform_state" {
  bucket        = aws_s3_bucket.terraform_state.id
  target_bucket = data.aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/terraform-state/"
}

resource "aws_s3_bucket_logging" "velero_backup" {
  bucket        = aws_s3_bucket.velero_backup.id
  target_bucket = data.aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/velero-backup/"
}

resource "aws_s3_bucket_logging" "teleport_sessions" {
  bucket        = aws_s3_bucket.teleport_sessions.id
  target_bucket = data.aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/teleport-sessions/"
}
