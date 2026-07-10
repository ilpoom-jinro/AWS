# =============================================
# #15 리소스 변경 추적 — Config 제거 후 CloudTrail이 이관받음.
# 실시간 Critical 알림은 #8 network_change + MAS 슬랙으로 커버.
#
# root 계정 활동 탐지(EventBridge·Metric Filter·Alarm)는 root_detection.tf.
# =============================================

# =============================================
# CloudWatch Log Group — CloudTrail 로그 수신
#
# CloudTrail이 이 Log Group에 로그를 전달해야 Metric Filter가 동작함.
# 보존 기간 90일: 전자금융거래법 최소 요건.
# =============================================
resource "aws_cloudwatch_log_group" "cloudtrail" {
  name              = "/aws/cloudtrail/ilpumjinro-trail"
  retention_in_days = 90

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "CloudTrail"
    Environment = "all"
  }
}

# IAM Role — CloudTrail → CloudWatch Logs 전달용
resource "aws_iam_role" "cloudtrail_cloudwatch" {
  name        = "financial-cloudtrail-cloudwatch-role"
  description = "CloudTrail to CloudWatch Logs delivery role for root activity monitoring"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowCloudTrail"
      Effect = "Allow"
      Principal = {
        Service = "cloudtrail.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "CloudTrail"
    Environment = "all"
  }
}

# CloudTrail이 Log Group에 로그 스트림 생성 및 이벤트 쓰기 권한
resource "aws_iam_role_policy" "cloudtrail_cloudwatch" {
  name = "financial-cloudtrail-cloudwatch-policy"
  role = aws_iam_role.cloudtrail_cloudwatch.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowCloudWatchLogsWrite"
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      # :* 는 Log Group 내 모든 Log Stream에 권한 부여 (CloudTrail 요구 사항)
      Resource = "${aws_cloudwatch_log_group.cloudtrail.arn}:*"
    }]
  })
}

# =============================================
# CloudTrail Trail
#
# event_selector: WriteOnly — Read 관리 이벤트 제외 → CloudWatch Logs 수집량·비용 감소.
#   유효값: ReadOnly / WriteOnly / All
#   Terraform이 소유하므로 CLI put-event-selectors 사용 금지(state 충돌).
# =============================================
resource "aws_cloudtrail" "main" {
  # cloudtrail 비활성화
  # count = 0

  name                          = "ilpumjinro-trail"
  s3_bucket_name                = "ilpumjinro-cloudtrail-logs-locked-v5"
  kms_key_id                    = var.kms_key_cloudtrail_arn
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true

  cloud_watch_logs_group_arn = "${aws_cloudwatch_log_group.cloudtrail.arn}:*"
  cloud_watch_logs_role_arn  = aws_iam_role.cloudtrail_cloudwatch.arn

  event_selector {
    read_write_type           = "WriteOnly"
    include_management_events = true
    # data_resource 없음 — 데이터 이벤트 미사용 (현 DataResources:[] 유지)
  }

  lifecycle {
    # advanced_event_selector: 미사용이나 외부 설정과의 충돌 방지를 위해 유지
    ignore_changes = [advanced_event_selector]
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "CloudTrail"
    Environment = "all"
  }
}
