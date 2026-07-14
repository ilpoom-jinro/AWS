output "api_anomaly_alert_sns_topic_arn" {
  description = "api-anomaly-alert SNS 토픽 ARN — Slack 담당자가 구독 추가 시 참조"
  value       = aws_sns_topic.api_anomaly_alert.arn
}

# ─────────────────────────────────────────────
# SIEM Athena 레이어 outputs
# ─────────────────────────────────────────────
output "siem_athena_workgroup" {
  description = "SIEM Athena 워크그룹 이름 — Athena Console에서 워크그룹 선택 시 참조"
  value       = aws_athena_workgroup.siem.name
}

output "siem_glue_database" {
  description = "SIEM Glue 데이터베이스 이름"
  value       = aws_glue_catalog_database.siem.name
}

output "siem_cloudtrail_table" {
  description = "CloudTrail Glue 테이블 이름"
  value       = aws_glue_catalog_table.cloudtrail.name
}

output "siem_alb_table" {
  description = "ALB Access Logs Glue 테이블 이름"
  value       = aws_glue_catalog_table.alb.name
}

output "siem_prowler_table" {
  description = "Prowler OCSF Glue 테이블 이름"
  value       = aws_glue_catalog_table.prowler.name
}

output "siem_athena_results_bucket_arn" {
  description = "SIEM Athena 쿼리 결과 버킷 ARN"
  value       = aws_s3_bucket.siem_athena_results.arn
}

output "siem_athena_query_role_arn" {
  description = "SIEM Athena 쿼리 전용 IAM 역할 ARN — 보안 담당자 AssumeRole 대상"
  value       = aws_iam_role.siem_athena_query.arn
}

# ─────────────────────────────────────────────
# #69 Break Glass 탐지 SNS ARN
# MAS 단계에서 Slack 구독 붙일 때 양 리전 토픽 모두 구독 필요
# ─────────────────────────────────────────────
output "breakglass_activity_alert_sns_topic_arn" {
  description = "Break Glass 탐지 SNS 토픽 ARN (ap-northeast-2) — MAS Slack 구독 참조용"
  value       = aws_sns_topic.breakglass_activity_alert.arn
}

output "breakglass_activity_alert_use1_sns_topic_arn" {
  description = "Break Glass 탐지 SNS 토픽 ARN (us-east-1) — MAS Slack 구독 참조용"
  value       = aws_sns_topic.breakglass_activity_alert_use1.arn
}

output "security_violation_alert_sns_topic_arn" {
  description = "IAM deny 위반/파괴적 시도 탐지 SNS 토픽 ARN — SecOps 트리거 구독 참조용"
  value       = aws_sns_topic.security_violation_alert.arn
}

output "network_change_alert_sns_topic_arn" {
  description = "SG/NACL/라우팅 변경 탐지 SNS 토픽 ARN — SecOps 트리거 구독 참조용"
  value       = aws_sns_topic.network_change_alert.arn
}

output "privilege_escalation_alert_use1_sns_topic_arn" {
  description = "권한상승/지속성 확보 탐지 SNS 토픽 ARN (us-east-1) — SecOps 트리거 크로스리전 구독 참조용"
  value       = aws_sns_topic.privilege_escalation_alert_use1.arn
}
