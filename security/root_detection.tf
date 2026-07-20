# =============================================
# AWS Root 계정 활동 탐지 인프라
#
# 목적: root 계정의 모든 활동을 탐지하고 SNS로 알림
#   1. EventBridge: root 콘솔 로그인 실시간 탐지
#   2. EventBridge: root API 호출 실시간 탐지
#   3. CloudWatch Metric Filter + Alarm: CloudTrail 로그 집계 기반 탐지
#      (CloudTrail 인프라는 cloudtrail.tf에서 관리)
#
# 두 레이어를 병행 사용하는 이유:
#   - EventBridge: 이벤트 발생 즉시 트리거 (실시간)
#   - Metric Filter: CloudTrail 로그 누락 시 백업 탐지 (신뢰성)
#
# MAS 단계에서 추가 예정:
#   - SNS → Slack 채널 연동 subscription
# =============================================

# =============================================
# SNS Topic - root 활동 알림 수신 (placeholder)
#
# SNS 암호화는 MAS에서 CMK로 root + network 두 토픽 동시 적용.
# aws/sns 관리형 키는 events.amazonaws.com / cloudwatch.amazonaws.com 의
# GenerateDataKey 권한이 없어 Publish 불가 → 현재 무암호화.
#
# 이메일 구독은 아래 aws_sns_topic_subscription으로 추가됨.
# MAS 단계에서 추가 예정:
#   - aws_sns_topic_subscription (Slack Lambda 또는 AWS Chatbot) — 이메일과 별개로 계속 예정
# =============================================
resource "aws_sns_topic" "root_activity_alert" {
  name              = "root-activity-alert"
  kms_master_key_id = var.key_sns_arn

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SNS"
    Environment = "all"
  }
}

# 이메일 구독 — 이 토픽은 secops-trigger.tf SQS 구독 대상에 아예 없어(breakglass와
# 동일 사유) 사람이 직접 받는 경로가 이거 하나뿐.
resource "aws_sns_topic_subscription" "root_activity_alert_email" {
  topic_arn = aws_sns_topic.root_activity_alert.arn
  protocol  = "email"
  endpoint  = var.alert_email
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
        # aws:SourceArn: root 탐지 룰 두 개만 발행 허용 (confused deputy 방지)
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.root_activity_alert.arn
        Condition = {
          ArnLike = {
            # root_console_login 은 us-east-1로 이동했으므로 여기선 제거
            "aws:SourceArn" = [
              aws_cloudwatch_event_rule.root_api_call.arn,
            ]
          }
          StringEquals = {
            "aws:SourceAccount" = var.account_id
          }
        }
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
  # root 콘솔 로그인은 무조건 us-east-1에 기록됨 → 규칙도 us-east-1에 있어야 트리거됨
  provider    = aws.us_east_1
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
# EventBridge Target — root API 호출 → SNS (ap-northeast-2)
# root_console_login 은 us-east-1로 이동했으므로 타깃도 아래 use1 블록에서 정의
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

# =============================================
# us-east-1 인프라 (#40 리전 버그 수정)
#
# root 글로벌 서비스 API(IAM 등) 호출은 us-east-1에 기록됨 → 규칙도 us-east-1 필요.
# root_console_login 은 이미 위에서 provider = aws.us_east_1 로 이동함.
# =============================================

resource "aws_cloudwatch_event_rule" "root_api_call_use1" {
  provider    = aws.us_east_1
  name        = "detect-root-api-call"
  description = "root 계정 AWS API 호출 탐지 (us-east-1)"

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
# SNS Topic — root 활동 알림 수신 (us-east-1)
#
# us-east-1 EventBridge 규칙의 타깃 SNS는 동일 리전이어야 함.
# 무암호화: root-activity-alert 와 동일 이유 (aws/sns 관리형 키에
# events.amazonaws.com GenerateDataKey 권한 없음).
# CMK 적용은 MAS에서 root/network 토픽과 함께 일괄 진행 예정.
# =============================================
resource "aws_sns_topic" "root_activity_alert_use1" {
  provider          = aws.us_east_1
  name              = "root-activity-alert-use1"
  kms_master_key_id = var.key_sns_arn

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SNS"
    Environment = "all"
  }
}

resource "aws_sns_topic_subscription" "root_activity_alert_use1_email" {
  provider  = aws.us_east_1
  topic_arn = aws_sns_topic.root_activity_alert_use1.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_policy" "root_activity_alert_use1" {
  provider = aws.us_east_1
  arn      = aws_sns_topic.root_activity_alert_use1.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
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
        Resource = aws_sns_topic.root_activity_alert_use1.arn
      },
      {
        # CloudWatch Alarm 은 ap-northeast-2 토픽만 씀 → AllowCloudWatchAlarmsPublish 불필요
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.root_activity_alert_use1.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = [
              aws_cloudwatch_event_rule.root_console_login.arn,
              aws_cloudwatch_event_rule.root_api_call_use1.arn,
            ]
          }
          StringEquals = {
            "aws:SourceAccount" = var.account_id
          }
        }
      }
    ]
  })
}

resource "aws_cloudwatch_event_target" "root_console_login_to_sns_use1" {
  provider  = aws.us_east_1
  rule      = aws_cloudwatch_event_rule.root_console_login.name
  target_id = "RootConsoleLoginToSNS"
  arn       = aws_sns_topic.root_activity_alert_use1.arn
}

resource "aws_cloudwatch_event_target" "root_api_call_to_sns_use1" {
  provider  = aws.us_east_1
  rule      = aws_cloudwatch_event_rule.root_api_call_use1.name
  target_id = "RootApiCallToSNS"
  arn       = aws_sns_topic.root_activity_alert_use1.arn
}
