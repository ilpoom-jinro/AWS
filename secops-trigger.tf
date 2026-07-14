# ──────────────────────────────────────────────────────────────────────────────
# SecOps 트리거 — 기존 보안 탐지(SNS) → SQS → (in-cluster) 워커 poller가 워크플로 기동
#
# GuardDuty(유료) 대신, 이미 인프라에 깔린 무료 탐지들을 재사용한다:
#   - security_alerts        : VPC Flow Logs REJECT 버스트 / DB포트 probe (CloudWatch 알람)
#   - security_violation_alert: IAM deny 위반 / 파괴적 시도 (EventBridge+CloudTrail)
#   - network_change_alert   : SG/NACL/라우팅 변경 (EventBridge+CloudTrail)
#   - api_anomaly_alert      : AccessDenied 급증 / 대량 Delete (CloudWatch 알람)
# 전부 CloudTrail 관리이벤트·Flow Logs 기반 = 추가 유료 서비스 없음.
#
# 아키텍처 근거:
#   - Temporal frontend는 ops 클러스터 내부 ClusterIP → VPC 밖에서 직접 못 붙음.
#   - ops VPC는 격리망(IGW/NAT 없음) → SQS 도달엔 SQS VPC 엔드포인트 필요
#     (vpc/ops/endpoints.tf의 aws_vpc_endpoint.sqs). wafv2 때와 동일 격리망 제약.
#   → 기존 탐지 SNS를 SQS로 팬아웃하고, SecOps 워커(in-cluster)가 SQS를 폴링해
#     기존 Temporal client로 워크플로를 기동. Temporal은 내부에 유지.
#
# 앱 레인 인터페이스(합의): SQS 메시지 body = 각 소스의 원본 메시지(raw delivery).
#   - CloudTrail 유래(network_change/iam_violation): EventBridge 이벤트 JSON
#     → 실제 CloudTrail Event ID 포함(증적 결선에 사용).
#   - 알람 유래(security_alerts/api_anomaly): CloudWatch Alarm JSON(신호). 상세는
#     워커가 텔레메트리 권한으로 Flow Logs/CloudTrail 재조회해 보강.
# ──────────────────────────────────────────────────────────────────────────────

# SecOps 워크플로를 기동시킬 기존 보안 탐지 SNS 토픽들 (전부 무료 소스)
locals {
  secops_source_sns_topics = {
    # security_alerts는 root(flowlogs.tf), 나머지는 module.security output 경유
    flow_logs      = aws_sns_topic.security_alerts.arn
    iam_violation  = module.security.security_violation_alert_sns_topic_arn
    network_change = module.security.network_change_alert_sns_topic_arn
    api_anomaly    = module.security.api_anomaly_alert_sns_topic_arn
    # 권한상승 신호도 태우려면 주석 해제:
    # breakglass   = module.security.breakglass_activity_alert_sns_topic_arn
  }
}

# 처리 실패 메시지 보관 (원인 분석용)
resource "aws_sqs_queue" "secops_trigger_dlq" {
  name                      = "financial-secops-trigger-dlq"
  message_retention_seconds = 1209600 # 14일

  # SSE-SQS(관리형 SSE) — SNS→SQS 전달과 호환되며 별도 KMS 키 정책 불필요.
  # 미설정 시 trivy AVD-AWS-0096(HIGH)로 IaC 스캔 실패.
  sqs_managed_sse_enabled = true

  tags = {
    Name      = "financial-secops-trigger-dlq"
    ManagedBy = "terraform"
  }
}

resource "aws_sqs_queue" "secops_trigger" {
  name = "financial-secops-trigger"
  # 워커가 워크플로 기동에 걸리는 시간 여유 (기동 실패 시 재수신 방지)
  visibility_timeout_seconds = 300
  message_retention_seconds  = 345600 # 4일

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.secops_trigger_dlq.arn
    maxReceiveCount     = 5
  })

  # SSE-SQS(관리형 SSE) — SNS→SQS 전달 호환 + KMS 키 정책 불필요. (AVD-AWS-0096 대응)
  sqs_managed_sse_enabled = true

  tags = {
    Name      = "financial-secops-trigger"
    ManagedBy = "terraform"
  }
}

# 위 보안 SNS 토픽들만 이 큐로 SendMessage 하도록 허용 (SourceArn 제한)
data "aws_iam_policy_document" "secops_trigger_queue" {
  statement {
    sid    = "AllowSecuritySnsSend"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.secops_trigger.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      # us-east-1 전용 소스(privilege_escalation_use1)는 리전이 달라 위 locals의
      # for_each 구독(default provider)에 못 태우므로 별도로 추가.
      values = concat(
        values(local.secops_source_sns_topics),
        [module.security.privilege_escalation_alert_use1_sns_topic_arn],
      )
    }
  }
}

resource "aws_sqs_queue_policy" "secops_trigger" {
  queue_url = aws_sqs_queue.secops_trigger.id
  policy    = data.aws_iam_policy_document.secops_trigger_queue.json
}

# 각 보안 SNS 토픽을 SecOps 트리거 SQS에 구독. raw_message_delivery=true로
# SNS 봉투를 벗겨 원본 메시지만 큐에 넣는다(워커 파싱 단순화).
resource "aws_sns_topic_subscription" "secops_trigger" {
  for_each             = local.secops_source_sns_topics
  topic_arn            = each.value
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.secops_trigger.arn
  raw_message_delivery = true
}

# us-east-1 SNS(privilege_escalation_use1) → ap-northeast-2 SQS 크로스리전 구독.
# AWS 요구사항: Subscribe 호출은 SNS 토픽이 있는 리전(us-east-1)에서 수행해야 함
# → provider를 명시해야 하므로 위 for_each 리소스(default provider)에 못 태우고 분리.
resource "aws_sns_topic_subscription" "secops_trigger_use1" {
  provider             = aws.us_east_1
  topic_arn            = module.security.privilege_escalation_alert_use1_sns_topic_arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.secops_trigger.arn
  raw_message_delivery = true
}

# 워커 poller가 소비할 큐. URL은 결정적(리전+계정+큐명)이라 configmap
# 템플릿(REPLACE_WITH_ACCOUNT_ID)으로 주입한다.
# 소비 권한(sqs:ReceiveMessage/DeleteMessage/GetQueueAttributes)은 SecOps 전용
# IAM role(secops-role.tf, 팀원 소유)에 아래 ARN 대상으로 추가되어야 한다.
output "secops_trigger_queue_arn" {
  description = "SecOps 트리거 SQS 큐 ARN (secops-role.tf의 sqs 소비 권한 대상)"
  value       = aws_sqs_queue.secops_trigger.arn
}

output "secops_trigger_queue_url" {
  description = "SecOps 트리거 SQS 큐 URL (워커 poller env)"
  value       = aws_sqs_queue.secops_trigger.id
}
