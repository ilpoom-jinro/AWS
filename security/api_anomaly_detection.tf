# =============================================
# #18 API 호출 추적 — CloudTrail 기반 이상 API 호출 탐지
#
# root_detection.tf 패턴 동일:
#   metric filter → alarm → SNS 토픽 (구독은 코드 밖)
#
# 탐지 대상:
#   (a) AccessDenied 급증: errorCode = *AccessDenied* / UnauthorizedOperation
#   (b) Delete* 급증:      eventName = Delete*
#
# ⚠️ 임계값 기본 제안 — baseline 관측 후 확정 필요:
#   AccessDenied: 5분 내 10건 초과 (평시 소량 발생 감안 → 높게)
#   Delete*:      5분 내  5건 초과 (삭제 이벤트는 드물어 → 낮게)
#
# ⚠️ CloudTrail event_selector = WriteOnly 설정으로 인해
#   READ 작업의 AccessDenied(GetObject 거부 등)는 이 필터에 집계되지 않음.
#   읽기 레벨까지 잡으려면 cloudtrail.tf의 read_write_type = "All" 변경 필요 (별도 결정).
#
# SNS 암호화: MAS에서 CMK 적용 예정 (root_activity_alert와 동일 이유)
# =============================================

# ─────────────────────────────────────────────────────
# SNS Topic — AccessDenied + Delete* 공용
#
# root_activity_alert와 분리한 이유:
#   - 토픽별 독립 구독 (Slack 채널 분리 가능)
#   - 중요도 구분: root 활동은 최우선 대응, API 이상은 모니터링 수준
#
# MAS 단계에서 추가 예정:
#   - SNS → Slack 채널 연동 subscription
# ─────────────────────────────────────────────────────
resource "aws_sns_topic" "api_anomaly_alert" {
  name              = "api-anomaly-alert"
  kms_master_key_id = var.key_sns_arn

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SNS"
    Environment = "all"
  }
}

# ─────────────────────────────────────────────────────
# SNS Topic Policy — 발행 권한 부여
#
# SNS에 명시적 정책을 붙이면 기본 정책이 완전히 대체됨
# → AllowAccountOwner 반드시 포함 (root_activity_alert 동일 패턴)
# ─────────────────────────────────────────────────────
resource "aws_sns_topic_policy" "api_anomaly_alert" {
  arn = aws_sns_topic.api_anomaly_alert.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 계정 root가 SNS Topic 관리 권한 보유 (락아웃 방지)
        # SNS:* 불가 - Topic 정책에는 topic-level 액션만 허용됨
        Sid    = "AllowAccountOwner"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.account_id}:root"
        }
        Action = [
          "SNS:GetTopicAttributes",
          "SNS:SetTopicAttributes",
          "SNS:AddPermission",
          "SNS:RemovePermission",
          "SNS:DeleteTopic",
          "SNS:Subscribe",
          "SNS:ListSubscriptionsByTopic",
          "SNS:Publish",
          "SNS:Receive"
        ]
        Resource = aws_sns_topic.api_anomaly_alert.arn
      },
      {
        # CloudWatch Alarm이 ALARM 상태 전환 시 SNS에 메시지 발행
        Sid    = "AllowCloudWatchAlarmsPublish"
        Effect = "Allow"
        Principal = {
          Service = "cloudwatch.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.api_anomaly_alert.arn
      }
    ]
  })
}

# ─────────────────────────────────────────────────────
# (a) AccessDenied 급증 탐지
# ─────────────────────────────────────────────────────
resource "aws_cloudwatch_log_metric_filter" "access_denied" {
  name           = "AccessDeniedMetricFilter"
  log_group_name = aws_cloudwatch_log_group.cloudtrail.name

  # errorCode가 *AccessDenied* 또는 UnauthorizedOperation인 이벤트
  pattern = "{ ($.errorCode = \"*AccessDenied*\") || ($.errorCode = \"UnauthorizedOperation\") }"

  metric_transformation {
    name          = "AccessDeniedCount"
    namespace     = "Security/ApiAnomaly"
    value         = "1"
    default_value = "0" # 무이벤트 구간 0 → INSUFFICIENT_DATA 방지
  }
}

# ⚠️ 임계값 10건/5분 — baseline 관측 후 조정 (제안값)
resource "aws_cloudwatch_metric_alarm" "access_denied" {
  alarm_name          = "AccessDeniedAlarm"
  alarm_description   = "5분 내 AccessDenied/UnauthorizedOperation 10건 초과 — 권한 오설정 또는 자격증명 탈취 의심"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.access_denied.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.access_denied.metric_transformation[0].namespace
  # root_activity는 period=60(1분). AccessDenied는 평시 소량 발생 → 5분 윈도우로 잡음 감소
  period             = 300
  statistic          = "Sum"
  threshold          = 10 # ⚠️ 제안값 — 확정 전 조정
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.api_anomaly_alert.arn]
  ok_actions    = []

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "CloudWatch"
    Environment = "all"
  }
}

# ─────────────────────────────────────────────────────
# (b) Delete* 급증 탐지
# ─────────────────────────────────────────────────────
resource "aws_cloudwatch_log_metric_filter" "delete_events" {
  name           = "DeleteEventsMetricFilter"
  log_group_name = aws_cloudwatch_log_group.cloudtrail.name

  # eventName이 Delete로 시작하는 모든 이벤트
  # (DeleteBucket, DeleteObject, DeleteRule, DeleteKey 등 전체 포함)
  pattern = "{ $.eventName = \"Delete*\" }"

  metric_transformation {
    name          = "DeleteEventCount"
    namespace     = "Security/ApiAnomaly"
    value         = "1"
    default_value = "0"
  }
}

# ⚠️ 임계값 5건/5분 — baseline 관측 후 조정 (제안값)
resource "aws_cloudwatch_metric_alarm" "delete_events" {
  alarm_name          = "DeleteEventsAlarm"
  alarm_description   = "5분 내 Delete* 이벤트 5건 초과 — 대량 삭제 또는 파괴적 API 호출 탐지"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.delete_events.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.delete_events.metric_transformation[0].namespace
  period              = 300
  statistic           = "Sum"
  threshold           = 5 # ⚠️ 제안값 — 확정 전 조정
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.api_anomaly_alert.arn]
  ok_actions    = []

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "CloudWatch"
    Environment = "all"
  }
}

# ─────────────────────────────────────────────────────
# MAS 단계 Slack 연동 (주석 — 활성화 시 적용)
# root_detection.tf의 MAS 주석과 동일 패턴
# ─────────────────────────────────────────────────────

# [방법 A] AWS Chatbot을 통한 Slack 연동
# resource "aws_chatbot_slack_channel_configuration" "api_anomaly_alert" {
#   configuration_name = "api-anomaly-slack-alert"
#   iam_role_arn       = aws_iam_role.chatbot_role.arn
#   slack_team_id      = var.slack_team_id
#   slack_channel_id   = var.slack_channel_id
#   sns_topic_arns     = [aws_sns_topic.api_anomaly_alert.arn]
# }

# [방법 B] SNS → Lambda → Slack Incoming Webhook
# resource "aws_sns_topic_subscription" "api_anomaly_alert_slack" {
#   topic_arn = aws_sns_topic.api_anomaly_alert.arn
#   protocol  = "lambda"
#   endpoint  = aws_lambda_function.slack_notifier.arn
# }
