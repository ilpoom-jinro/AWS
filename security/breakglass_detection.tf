# =============================================
# #69 Break Glass Role 사용 탐지
#
# financial-kms-breakglass-role 에 대한 sts:AssumeRole 을 실시간 탐지.
# assume 경로에 따라 이벤트 기록 리전이 갈리므로
# (콘솔/글로벌 엔드포인트=us-east-1, CLI v2 리전 엔드포인트=ap-northeast-2)
# 양 리전에 규칙·토픽을 둔다.
#
# errorCode 필터 없음 = 성공+실패 모두 매칭
# (실패=MFA 미충족 또는 무단 사용자의 시도이므로 반드시 잡아야 함)
# SNS 무암호화: CMK 암호화는 MAS에서 일괄 적용 예정.
# =============================================

locals {
  breakglass_role_arn_suffix = "/financial-kms-breakglass-role"
}

# =============================================
# EventBridge 규칙 — ap-northeast-2
#
# roleArn suffix 매칭 → account_id 하드코딩 없이 역할 특정
# errorCode 미포함 → EventBridge 해당 필드 무시 = 성공·실패 모두 매칭
# =============================================
resource "aws_cloudwatch_event_rule" "breakglass_assume_role" {
  name        = "detect-breakglass-assume-role"
  description = "#69 Break Glass Role AssumeRole 탐지 (ap-northeast-2)"

  event_pattern = jsonencode({
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource = ["sts.amazonaws.com"]
      eventName   = ["AssumeRole"]
      requestParameters = {
        roleArn = [{ suffix = local.breakglass_role_arn_suffix }]
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
# EventBridge 규칙 — us-east-1 (동일 패턴)
# =============================================
resource "aws_cloudwatch_event_rule" "breakglass_assume_role_use1" {
  provider    = aws.us_east_1
  name        = "detect-breakglass-assume-role"
  description = "#69 Break Glass Role AssumeRole 탐지 (us-east-1)"

  event_pattern = jsonencode({
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource = ["sts.amazonaws.com"]
      eventName   = ["AssumeRole"]
      requestParameters = {
        roleArn = [{ suffix = local.breakglass_role_arn_suffix }]
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
# SNS 토픽 (리전별)
#
# 무암호화: aws/sns 관리형 키에 events.amazonaws.com GenerateDataKey 권한 없음.
# root-activity-alert 와 동일 이유. CMK는 MAS에서 일괄 적용 예정.
# =============================================
resource "aws_sns_topic" "breakglass_activity_alert" {
  name              = "breakglass-activity-alert"
  kms_master_key_id = var.key_sns_arn

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SNS"
    Environment = "all"
  }
}

# 이메일 구독 — 이 토픽은 secops-trigger.tf SQS 구독 대상에서 빠져 있어(주석 처리됨,
# MAS 단계 예정) 사람이 직접 받는 경로가 이거 하나뿐. 구독 생성 후 AWS가 보내는
# 확인 메일을 실제로 클릭해야 알림이 온다.
resource "aws_sns_topic_subscription" "breakglass_activity_alert_email" {
  topic_arn = aws_sns_topic.breakglass_activity_alert.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic" "breakglass_activity_alert_use1" {
  provider          = aws.us_east_1
  name              = "breakglass-activity-alert-use1"
  kms_master_key_id = var.key_sns_arn

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SNS"
    Environment = "all"
  }
}

resource "aws_sns_topic_subscription" "breakglass_activity_alert_use1_email" {
  provider  = aws.us_east_1
  topic_arn = aws_sns_topic.breakglass_activity_alert_use1.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# =============================================
# SNS 정책 (리전별)
# AllowAccountOwner + AllowEventBridgePublish(해당 리전 규칙만 SourceArn 지정)
# =============================================
resource "aws_sns_topic_policy" "breakglass_activity_alert" {
  arn = aws_sns_topic.breakglass_activity_alert.arn

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
        Resource = aws_sns_topic.breakglass_activity_alert.arn
      },
      {
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.breakglass_activity_alert.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = [aws_cloudwatch_event_rule.breakglass_assume_role.arn]
          }
          StringEquals = {
            "aws:SourceAccount" = var.account_id
          }
        }
      }
    ]
  })
}

resource "aws_sns_topic_policy" "breakglass_activity_alert_use1" {
  provider = aws.us_east_1
  arn      = aws_sns_topic.breakglass_activity_alert_use1.arn

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
        Resource = aws_sns_topic.breakglass_activity_alert_use1.arn
      },
      {
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.breakglass_activity_alert_use1.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = [aws_cloudwatch_event_rule.breakglass_assume_role_use1.arn]
          }
          StringEquals = {
            "aws:SourceAccount" = var.account_id
          }
        }
      }
    ]
  })
}

# =============================================
# EventBridge 타깃 (input_transformer — 성공/실패 구분 메시지)
#
# 성공 이벤트는 errorCode 필드 자체가 없으므로
# 수신 메시지에 "결과=<errorCode>" 리터럴이 출력됨 (EventBridge 동작).
# 실패 시엔 "결과=AccessDenied".
# =============================================
resource "aws_cloudwatch_event_target" "breakglass_to_sns" {
  rule      = aws_cloudwatch_event_rule.breakglass_assume_role.name
  target_id = "BreakGlassToSNS"
  arn       = aws_sns_topic.breakglass_activity_alert.arn

  input_transformer {
    input_paths = {
      time      = "$.time"
      region    = "$.region"
      principal = "$.detail.userIdentity.arn"
      errorCode = "$.detail.errorCode"
    }
    input_template = "\"[Break Glass] AssumeRole 감지 | 시각=<time> | 주체=<principal> | 리전=<region> | 결과=<errorCode>\""
  }
}

resource "aws_cloudwatch_event_target" "breakglass_to_sns_use1" {
  provider  = aws.us_east_1
  rule      = aws_cloudwatch_event_rule.breakglass_assume_role_use1.name
  target_id = "BreakGlassToSNS"
  arn       = aws_sns_topic.breakglass_activity_alert_use1.arn

  input_transformer {
    input_paths = {
      time      = "$.time"
      region    = "$.region"
      principal = "$.detail.userIdentity.arn"
      errorCode = "$.detail.errorCode"
    }
    input_template = "\"[Break Glass] AssumeRole 감지 | 시각=<time> | 주체=<principal> | 리전=<region> | 결과=<errorCode>\""
  }
}
