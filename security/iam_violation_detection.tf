# =============================================
# #49 deny 정책 위반 시도 탐지
#
# IAM explicit deny로 차단된 API 호출은 CloudTrail에
# errorCode = "AccessDenied"로 기록됨 → EventBridge 매칭 → SNS 알림
#
# 대상 deny 정책:
#   - deny_create_access_key : iam:CreateAccessKey
#   - deny_cloudshell        : cloudshell:* (eventName 핀포인트 제외 — 첫 거부가
#                              GetEnvironmentStatus일 수 있어 source 레벨로만 탐지)
#   - deny_destructive       : ec2:TerminateInstances, rds:DeleteDBInstance,
#                              eks:DeleteCluster, s3:DeleteBucket,
#                              iam:DeleteUser, iam:DeleteRole
#   - require_mfa 제외       : STS 레벨 차단이라 탐지 불안정
#
# 전제:
#   key_sns는 kms/kms.tf에서 관리 (별도 state), events.amazonaws.com
#   Statement가 있어야 EventBridge publish 시 KMS 거부 없이 동작함
# =============================================

# =============================================
# SNS Topic — deny 위반 알림 (key-sns 암호화)
#
# 기존 root-activity-alert / network-change-alert는 평문이지만
# 신규 토픽은 key-sns CMK 적용 (var.key_sns_arn: 루트에서 전달)
# =============================================
resource "aws_sns_topic" "security_violation_alert" {
  name              = "security-violation-alert"
  kms_master_key_id = var.key_sns_arn

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SNS"
    Environment = "all"
  }
}

# =============================================
# SNS Topic Policy — 발행 권한 부여
#
# SNS에 명시적 정책을 붙이면 기본 정책이 완전히 대체되므로
# 계정 소유자 권한(AllowAccountOwner)을 반드시 포함해야 함
# SourceArn을 룰 ARN으로 직접 지정해 이 두 룰만 발행 허용 (confused deputy 방지)
# =============================================
resource "aws_sns_topic_policy" "security_violation_alert" {
  arn = aws_sns_topic.security_violation_alert.arn

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
        Resource = aws_sns_topic.security_violation_alert.arn
      },
      {
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.security_violation_alert.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = [
              aws_cloudwatch_event_rule.iam_violation.arn,
              aws_cloudwatch_event_rule.destructive_violation.arn,
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

# =============================================
# EventBridge Rule A — IAM 위반 탐지
#   deny_create_access_key: iam:CreateAccessKey AccessDenied
#   deny_cloudshell:        cloudshell.amazonaws.com AccessDenied
#
# $or로 (eventSource, eventName) 쌍을 정밀 매칭
# cloudshell은 eventName 생략 — cloudshell:* deny라 첫 호출이
# GetEnvironmentStatus일 수 있어 source만으로 탐지
# =============================================
resource "aws_cloudwatch_event_rule" "iam_violation" {
  name        = "detect-iam-deny-violation"
  description = "#49 deny_create_access_key / deny_cloudshell 위반 시도 탐지"

  event_pattern = jsonencode({
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      errorCode = ["AccessDenied"]
      "$or" = [
        { eventSource = ["iam.amazonaws.com"], eventName = ["CreateAccessKey"] },
        { eventSource = ["cloudshell.amazonaws.com"] }
      ]
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

resource "aws_cloudwatch_event_target" "iam_violation_to_sns" {
  rule      = aws_cloudwatch_event_rule.iam_violation.name
  target_id = "IamViolationToSNS"
  arn       = aws_sns_topic.security_violation_alert.arn
}

# =============================================
# EventBridge Rule B — 인프라 파괴 시도 탐지
#   deny_destructive가 막는 6개 액션을 $or로 정밀 매칭
#   eks:DeleteCluster는 ecs:DeleteCluster 등과 구분하기 위해
#   eventSource = eks.amazonaws.com 으로 한정
# =============================================
resource "aws_cloudwatch_event_rule" "destructive_violation" {
  name        = "detect-destructive-deny-violation"
  description = "#49 deny_destructive 위반 시도 탐지 (terminate/delete AccessDenied)"

  event_pattern = jsonencode({
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      errorCode = ["AccessDenied"]
      "$or" = [
        { eventSource = ["ec2.amazonaws.com"], eventName = ["TerminateInstances"] },
        { eventSource = ["rds.amazonaws.com"], eventName = ["DeleteDBInstance"] },
        { eventSource = ["eks.amazonaws.com"], eventName = ["DeleteCluster"] },
        { eventSource = ["s3.amazonaws.com"], eventName = ["DeleteBucket"] },
        { eventSource = ["iam.amazonaws.com"], eventName = ["DeleteUser", "DeleteRole"] }
      ]
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

resource "aws_cloudwatch_event_target" "destructive_violation_to_sns" {
  rule      = aws_cloudwatch_event_rule.destructive_violation.name
  target_id = "DestructiveViolationToSNS"
  arn       = aws_sns_topic.security_violation_alert.arn
}

# =============================================
# EventBridge Rule C — 권한 상승/지속성 확보 탐지 (계정 탈취 체인, us-east-1)
#
#   IAM은 글로벌 서비스라 관리이벤트가 us-east-1 EventBridge에서만 발생한다
#   (root_console_login과 동일 이유, root_detection.tf 참조) — ap-northeast-2 룰로는
#   절대 트리거되지 않아 리전을 옮김.
#
#   errorCode 조건 없음 — 계정 탈취는 "성공한" 권한부여·AccessKey 생성으로 지속성을
#   확보하는 체인이라 거부(AccessDenied)만 잡는 iam_violation으로는 놓친다.
#
#   EventBridge 타겟은 룰과 동일 리전이어야 해서(이벤트 버스 타겟 제외) SecOps SQS
#   (ap-northeast-2)를 직접 타겟할 수 없다 — us-east-1 전용 SNS를 두고
#   크로스리전 SNS→SQS 구독으로 우회한다(구독은 secops-trigger.tf에서 정의).
# =============================================
resource "aws_sns_topic" "privilege_escalation_alert_use1" {
  provider = aws.us_east_1
  name     = "privilege-escalation-alert-use1"
  # 무암호화: network_change_alert와 동일 이유 — aws/sns 관리형 키에
  # events.amazonaws.com GenerateDataKey 권한이 없어 CMK 적용 시 EventBridge
  # 발행이 막힌다. CMK 적용은 MAS 단계에서 검토.

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SNS"
    Environment = "all"
  }
}

resource "aws_sns_topic_policy" "privilege_escalation_alert_use1" {
  provider = aws.us_east_1
  arn      = aws_sns_topic.privilege_escalation_alert_use1.arn

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
        Resource = aws_sns_topic.privilege_escalation_alert_use1.arn
      },
      {
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.privilege_escalation_alert_use1.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_cloudwatch_event_rule.privilege_escalation_use1.arn
          }
          StringEquals = {
            "aws:SourceAccount" = var.account_id
          }
        }
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "privilege_escalation_use1" {
  provider    = aws.us_east_1
  name        = "detect-privilege-escalation"
  description = "계정 탈취 대응 — 성공한 AccessKey 생성 탐지 (us-east-1). Admin 권한부여는 워크플로우 lookback이 조회."

  event_pattern = jsonencode({
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource = ["iam.amazonaws.com"]
      eventName = [
        "CreateAccessKey",
      ]
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

resource "aws_cloudwatch_event_target" "privilege_escalation_use1_to_sns" {
  provider  = aws.us_east_1
  rule      = aws_cloudwatch_event_rule.privilege_escalation_use1.name
  target_id = "PrivilegeEscalationToSNS"
  arn       = aws_sns_topic.privilege_escalation_alert_use1.arn
}
