# =============================================
# AWS Root 계정 활동 탐지 인프라
#
# 목적: root 계정의 모든 활동을 탐지하고 SNS로 알림
#   1. EventBridge: root 콘솔 로그인 실시간 탐지
#   2. EventBridge: root API 호출 실시간 탐지
#   3. CloudWatch Metric Filter + Alarm: CloudTrail 로그 집계 기반 탐지
#
# 두 레이어를 병행 사용하는 이유:
#   - EventBridge: 이벤트 발생 즉시 트리거 (실시간)
#   - Metric Filter: CloudTrail 로그 누락 시 백업 탐지 (신뢰성)
#
# MAS 단계에서 추가 예정:
#   - SNS → Slack 채널 연동 subscription
# =============================================

# =============================================
# CloudWatch Log Group - CloudTrail 로그 수신
#
# CloudTrail이 이 Log Group에 로그를 전달해야 Metric Filter가 동작함
# 보존 기간 90일: 금융권 규정(전자금융거래법) 최소 요건
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

# IAM Role - CloudTrail → CloudWatch Logs 전달용
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
# CloudTrail Trail - 기존 Trail Terraform 관리
#
# 신규 계정: 기존 Trail이 없으므로 import 불필요, Terraform이 새로 생성.
# kms_key_id 미지정 시 버킷의 SSE-S3(AES256) 기본 암호화 적용 (bootstrap/main.tf 참고).
# 추후 금융권 CMK 정책 적용 시 kms.tf 패턴을 따라 CloudTrail 전용 CMK를 생성해 연결.
# 최초 1회 import 필요 (기존 계정):
#   terraform import module.security.aws_cloudtrail.main \
#     arn:aws:cloudtrail:ap-northeast-2:<ACCOUNT_ID>:trail/ilpumjinro-trail
#
# lifecycle ignore_changes 이유:
#   기존 Trail에 HasCustomEventSelectors=true 설정 존재.
#   Terraform이 event selector를 빈 값으로 덮어쓰면
#   InvalidEventSelectorsException 발생 → 변경 무시로 해결.
# =============================================
resource "aws_cloudtrail" "main" {
  name                          = "ilpumjinro-trail"
  s3_bucket_name                = "ilpumjinro-cloudtrail-logs-locked-v2"
  kms_key_id                    = var.kms_key_cloudtrail_arn
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true

  cloud_watch_logs_group_arn = "${aws_cloudwatch_log_group.cloudtrail.arn}:*"
  cloud_watch_logs_role_arn  = aws_iam_role.cloudtrail_cloudwatch.arn

  lifecycle {
    ignore_changes = [event_selector, advanced_event_selector]
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "CloudTrail"
    Environment = "all"
  }
}

# =============================================
# SNS Topic - root 활동 알림 수신 (placeholder)
#
# kms_master_key_id: AWS 관리형 SNS 키 사용
#   - 기존 프로젝트 KMS 키(RDS 전용)와 분리
#   - MAS 단계에서 CMK로 교체 시 키 정책에 SNS 서비스 추가 필요
#
# MAS 단계에서 추가 예정:
#   - aws_sns_topic_subscription (Slack Lambda 또는 AWS Chatbot)
# =============================================
resource "aws_sns_topic" "root_activity_alert" {
  name              = "root-activity-alert"
  kms_master_key_id = "alias/aws/sns"

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SNS"
    Environment = "all"
  }
}

# =============================================
# SNS Topic Policy - 발행 권한 부여
#
# SNS에 명시적 정책을 붙이면 기본 정책이 완전히 대체되므로
# 계정 소유자 권한(AllowAccountOwner)을 반드시 포함해야 함
# =============================================
resource "aws_sns_topic_policy" "root_activity_alert" {
  arn = aws_sns_topic.root_activity_alert.arn

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
        Resource = aws_sns_topic.root_activity_alert.arn
      },
      {
        # EventBridge가 Rule 트리거 시 SNS에 메시지 발행
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.root_activity_alert.arn
      },
      {
        # CloudWatch Alarm이 ALARM 상태 전환 시 SNS에 메시지 발행
        Sid    = "AllowCloudWatchAlarmsPublish"
        Effect = "Allow"
        Principal = {
          Service = "cloudwatch.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.root_activity_alert.arn
      }
    ]
  })
}

# =============================================
# EventBridge Rule #1 - root 콘솔 로그인 탐지
#
# aws.signin 소스의 ConsoleLogin 이벤트 중
# userIdentity.type = "Root"인 경우만 트리거
# =============================================
resource "aws_cloudwatch_event_rule" "root_console_login" {
  name        = "detect-root-console-login"
  description = "root 계정 콘솔 로그인 탐지"

  event_pattern = jsonencode({
    source        = ["aws.signin"]
    "detail-type" = ["AWS Console Sign In via CloudTrail"]
    detail = {
      userIdentity = {
        type = ["Root"]
      }
    }
  })

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "EventBridge"
    Environment = "all"
  }
}

# =============================================
# EventBridge Rule #2 - root 계정 API 호출 탐지
#
# root 계정이 발생시킨 모든 AWS API 호출 탐지
# aws.signin(콘솔 로그인)은 Rule #1에서 처리하므로 제외
# =============================================
resource "aws_cloudwatch_event_rule" "root_api_call" {
  name        = "detect-root-api-call"
  description = "root 계정 AWS API 호출 탐지"

  event_pattern = jsonencode({
    source = [{
      "anything-but" = ["aws.signin"]
    }]
    detail = {
      userIdentity = {
        type = ["Root"]
      }
    }
  })

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "EventBridge"
    Environment = "all"
  }
}

# =============================================
# EventBridge Target #1 - root 콘솔 로그인 → SNS
# =============================================
resource "aws_cloudwatch_event_target" "root_console_login_to_sns" {
  rule      = aws_cloudwatch_event_rule.root_console_login.name
  target_id = "RootConsoleLoginToSNS"
  arn       = aws_sns_topic.root_activity_alert.arn
}

# =============================================
# EventBridge Target #2 - root API 호출 → SNS
# =============================================
resource "aws_cloudwatch_event_target" "root_api_call_to_sns" {
  rule      = aws_cloudwatch_event_rule.root_api_call.name
  target_id = "RootApiCallToSNS"
  arn       = aws_sns_topic.root_activity_alert.arn
}

# =============================================
# CloudWatch Log Metric Filter - root 활동 필터
#
# CloudTrail 로그에서 root 계정이 발생시킨 실제 API 호출만 집계
# 조건:
#   - userIdentity.type = "Root": root 계정 이벤트
#   - invokedBy NOT EXISTS: AWS 서비스가 자동 호출한 이벤트 제외
#   - eventType != "AwsServiceEvent": 서비스 내부 이벤트 제외
# =============================================
resource "aws_cloudwatch_log_metric_filter" "root_activity" {
  name           = "RootActivityMetricFilter"
  log_group_name = aws_cloudwatch_log_group.cloudtrail.name

  pattern = "{ ($.userIdentity.type = \"Root\") && ($.userIdentity.invokedBy NOT EXISTS) && ($.eventType != \"AwsServiceEvent\") }"

  metric_transformation {
    name      = "RootActivityCount"
    namespace = "Security/RootActivity"
    value     = "1"
  }
}

# =============================================
# CloudWatch Metric Alarm - root 활동 탐지 시 SNS 알림
#
# 1분 내 root 활동 1회 이상 감지 시 ALARM → SNS 발행
# treat_missing_data = "notBreaching": 데이터 없음(정상)을 ALARM으로 오해하지 않도록
# ok_actions = []: root 활동 자체가 이상 징후이므로 정상 복귀 알림 불필요
# =============================================
resource "aws_cloudwatch_metric_alarm" "root_activity" {
  alarm_name          = "RootActivityAlarm"
  alarm_description   = "root 계정 활동 탐지 - 즉시 확인 필요"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.root_activity.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.root_activity.metric_transformation[0].namespace
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.root_activity_alert.arn]
  ok_actions    = []

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "CloudWatch"
    Environment = "all"
  }
}

# =============================================
# MAS 단계 Slack 연동 (주석 - 활성화 시 적용)
#
# 방법 선택:
#   A) AWS Chatbot: 관리형 서비스, 설정 간단, Slack App 승인 필요
#   B) SNS → Lambda → Slack Webhook: 커스텀 메시지 포맷 가능
# =============================================

# [방법 A] AWS Chatbot을 통한 Slack 연동
# resource "aws_chatbot_slack_channel_configuration" "root_alert" {
#   configuration_name = "root-activity-slack-alert"
#   iam_role_arn       = aws_iam_role.chatbot_role.arn    # Chatbot 전용 IAM Role 별도 생성 필요
#   slack_team_id      = var.slack_team_id                 # Slack Workspace ID (variables.tf 추가 필요)
#   slack_channel_id   = var.slack_channel_id              # #security-alerts 채널 ID
#   sns_topic_arns     = [aws_sns_topic.root_activity_alert.arn]
# }

# [방법 B] SNS → Lambda → Slack Incoming Webhook
# resource "aws_sns_topic_subscription" "root_alert_slack" {
#   topic_arn = aws_sns_topic.root_activity_alert.arn
#   protocol  = "lambda"
#   endpoint  = aws_lambda_function.slack_notifier.arn    # Slack 알림 Lambda 별도 구성 필요
# }
