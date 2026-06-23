# =============================================
# 네트워크 변경 탐지 인프라 (#8)
#
# 목적: VPC/SG/NACL 설정 변경을 CloudTrail 관리 이벤트 기반으로 실시간 탐지
#   - EventBridge: CloudTrail write 이벤트 필터링 → SNS 발행
#   - SNS: 수신 엔드포인트 placeholder (MAS 단계에서 Lambda/Chatbot 구독 추가)
#
# CloudTrail 의존성:
#   ilpumjinro-trail 이 관리 이벤트(write)를 기록해야 EventBridge 가 매칭함.
#   CloudTrail 인프라(Trail·Log Group·IAM Role)는 cloudtrail.tf에서 관리.
#   event_selector = WriteOnly 로 Terraform 고정(cloudtrail.tf 참조).
# =============================================

# =============================================
# SNS Topic - 네트워크 변경 알림 수신
#
# SSE 의도적 미설정:
#   alias/aws/sns(관리형 키) 암호화 시 EventBridge 발행 불가
#   (관리형 키 정책이 events.amazonaws.com 에 kms:Decrypt/GenerateDataKey 미부여, 수정 불가).
#   암호화는 MAS 단계에서 CMK 생성 후 적용 — root-activity-alert 와 공유.
# =============================================
resource "aws_sns_topic" "network_change_alert" {
  name = "network-change-alert"

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
# SNS 에 명시적 정책을 붙이면 기본 정책이 완전히 대체되므로
# 계정 소유자 권한(AllowAccountOwner)을 반드시 포함해야 함
# =============================================
resource "aws_sns_topic_policy" "network_change_alert" {
  arn = aws_sns_topic.network_change_alert.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 계정 root 락아웃 방지 (topic-level 액션만 — SNS:* 불가)
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
        Resource = aws_sns_topic.network_change_alert.arn
      },
      {
        # EventBridge 룰 트리거 시 발행
        # aws:SourceArn: 이 토픽을 타깃으로 지정한 룰만 발행 허용 (confused deputy 방지)
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.network_change_alert.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_cloudwatch_event_rule.network_change.arn
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
# EventBridge Rule - VPC/SG/NACL 변경 탐지 (#8)
#
# CloudTrail 관리 이벤트 기반 — read-only 자동 제외, 변경 API 만 매칭.
# principal 필터(IaC role 제외)는 여기 안 넣음:
#   EventBridge 패턴은 지정 필드가 이벤트에 존재해야만 매칭 →
#   sessionContext 없는 IAM 유저/root 직접 변경이 통째로 누락됨(=가장 잡아야 할 무단 변경).
#   주체 기반 억제는 MAS 단계 알림 Lambda 에서 처리.
# =============================================
resource "aws_cloudwatch_event_rule" "network_change" {
  name        = "detect-network-change"
  description = "VPC/SG/NACL 변경 API 호출 탐지 (#8)"

  event_pattern = jsonencode({
    source        = ["aws.ec2"]
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      eventName = [
        # Security Group
        "AuthorizeSecurityGroupIngress",
        "AuthorizeSecurityGroupEgress",
        "RevokeSecurityGroupIngress",
        "RevokeSecurityGroupEgress",
        "CreateSecurityGroup",
        "DeleteSecurityGroup",
        "ModifySecurityGroupRules",
        # Network ACL
        "CreateNetworkAcl",
        "DeleteNetworkAcl",
        "CreateNetworkAclEntry",
        "DeleteNetworkAclEntry",
        "ReplaceNetworkAclEntry",
        "ReplaceNetworkAclAssociation",
        # VPC
        "CreateVpc",
        "DeleteVpc",
        "ModifyVpcAttribute",
        "CreateVpcPeeringConnection",
        "AcceptVpcPeeringConnection",
        "DeleteVpcPeeringConnection",
        # Internet Gateway — VPC 인터넷 연결 변경 (전자금융감독규정·ISMS-P 네트워크 보안)
        "CreateInternetGateway",
        "DeleteInternetGateway",
        "AttachInternetGateway",
        "DetachInternetGateway",
        # Route Table — private 서브넷에 IGW 경로 추가 시 인터넷 노출 가능
        "CreateRouteTable",
        "DeleteRouteTable",
        "AssociateRouteTable",
        "DisassociateRouteTable",
        "CreateRoute",
        "DeleteRoute",
        "ReplaceRoute",
        # Subnet — MapPublicIpOnLaunch 변경 시 신규 인스턴스 퍼블릭 IP 자동 할당
        "ModifySubnetAttribute"
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

# =============================================
# EventBridge Target - network_change → SNS
# =============================================
resource "aws_cloudwatch_event_target" "network_change_to_sns" {
  rule      = aws_cloudwatch_event_rule.network_change.name
  target_id = "NetworkChangeToSNS"
  arn       = aws_sns_topic.network_change_alert.arn
}

# =============================================
# MAS 단계 추가 예정:
#  1) SNS SSE — kms/ 모듈에 CMK 생성, 키 정책에 events.amazonaws.com kms:Decrypt/GenerateDataKey* 부여.
#     이 토픽 + root-activity-alert 둘 다 이 CMK 로 교체
#     (root_detection 의 alias/aws/sns 발행 불가 버그도 같이 수정).
#  2) SNS → Lambda → Slack 구독. Lambda 에서 주체 기반 억제:
#     호출자가 {IaC CodeBuild role, ALB Controller IRSA, 기타 예상 자동 주체}면 스킵, 아니면 발송.
#     ※ AWS Chatbot 아님 — Lambda 경로. Chatbot 은 주체 기반 필터링 불가.
# =============================================
