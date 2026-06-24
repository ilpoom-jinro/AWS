# =====================================================================
# flowlogs.tf (루트)
#   VPC Flow Logs (REJECT only) → CloudWatch Logs
#     - 로깅: vpc1~4 전부
#     - 알람: vpc1 만 (DB포트 probe / REJECT 버스트)
#     - 알림: SNS(key-sns 암호화), Slack 구독은 placeholder
#   선행조건: kms/ 가 먼저 apply 되어 alias/key-logs, alias/key-sns 존재
#   KMS 참조: data-kms.tf 의 data.aws_kms_key.key_logs / key_sns
# =====================================================================

# ---- 대상 VPC 맵 (모듈 출력 직접 참조) ----
locals {
  flowlog_vpcs = {
    vpc1 = module.vpc1.vpc_id # globalservice (IGW 有) — REJECT 多, 알람 대상
    vpc2 = module.vpc2.vpc_id # ops (완전 private) — REJECT≈0, 찍히면 망분리 신호
    vpc3 = module.vpc3.vpc_id # Teleport
    vpc4 = module.vpc4.vpc_id # Headscale
  }
}

# ---- Flow Logs → CW Logs 전송용 IAM 역할 (4개 VPC 공용) ----
# CW Logs 쓰기 권한만 필요. KMS 권한 불필요
# (암호화는 CloudWatch Logs 서비스가 key-logs 로 직접 처리하므로)
data "aws_iam_policy_document" "flowlogs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flowlogs" {
  name               = "vpc-flowlogs-to-cwlogs"
  assume_role_policy = data.aws_iam_policy_document.flowlogs_assume.json
  tags               = { Name = "vpc-flowlogs-to-cwlogs" }
}

data "aws_iam_policy_document" "flowlogs_publish" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    # TF가 로그그룹을 미리 생성하므로 CreateLogGroup 불필요
    resources = ["arn:aws:logs:*:*:log-group:/aws/vpc/flowlogs/*:*"]
  }
}

resource "aws_iam_role_policy" "flowlogs" {
  name   = "vpc-flowlogs-publish"
  role   = aws_iam_role.flowlogs.id
  policy = data.aws_iam_policy_document.flowlogs_publish.json
}

# ---- 로그그룹 ×4 (30일 보관, key-logs 암호화) ----
resource "aws_cloudwatch_log_group" "flowlogs" {
  for_each          = local.flowlog_vpcs
  name              = "/aws/vpc/flowlogs/${each.key}"
  retention_in_days = 30
  kms_key_id        = data.aws_kms_key.key_logs.arn
  tags              = { Name = "flowlogs-${each.key}" }
}

# ---- Flow Logs ×4 (REJECT only, 60초 집계) ----
resource "aws_flow_log" "this" {
  for_each                 = local.flowlog_vpcs
  vpc_id                   = each.value
  traffic_type             = "REJECT"
  log_destination_type     = "cloud-watch-logs"
  log_destination          = aws_cloudwatch_log_group.flowlogs[each.key].arn
  iam_role_arn             = aws_iam_role.flowlogs.arn
  max_aggregation_interval = 60 # 기본 600초→60초, 실시간성↑
  # log_format 미지정 — 기본 v2(14필드) 유지. 커스텀 포맷 시 아래 메트릭필터 패턴 깨짐
  tags = { Name = "flowlog-${each.key}" }
}

# ---- (A) VPC별 REJECT 카운트 메트릭 ×4 ----
# REJECT-only 그룹이라 전체 이벤트=전체 REJECT → 패턴 ""으로 전부 매칭
# 차원 없음(스칼라) → 커스텀 메트릭 무료 10개 내. baseline·비용 모니터링용
resource "aws_cloudwatch_log_metric_filter" "reject_count" {
  for_each       = local.flowlog_vpcs
  name           = "flowlogs-reject-count-${each.key}"
  log_group_name = aws_cloudwatch_log_group.flowlogs[each.key].name
  pattern        = ""

  metric_transformation {
    name          = "RejectCount"
    namespace     = "Security/FlowLogs/${each.key}"
    value         = "1"
    default_value = "0" # 무이벤트 구간 0 → 알람 INSUFFICIENT_DATA 방지
  }
}

# ---- (B) vpc1 DB포트 probe 메트릭 ----
# 기본 flow log 14필드(v2):
#   [version, account_id, interface_id, srcaddr, dstaddr, srcport, dstport,
#    protocol, packets, bytes, start, end, action, log_status]
resource "aws_cloudwatch_log_metric_filter" "db_port_probe_vpc1" {
  name           = "flowlogs-dbport-probe-vpc1"
  log_group_name = aws_cloudwatch_log_group.flowlogs["vpc1"].name

  pattern = "[version, account_id, interface_id, srcaddr, dstaddr, srcport, dstport=3306 || dstport=5432 || dstport=1433 || dstport=6379, protocol, packets, bytes, start, end, action, log_status]"

  metric_transformation {
    name          = "DbPortProbeCount"
    namespace     = "Security/FlowLogs/vpc1"
    value         = "1"
    default_value = "0"
  }
}

# ---- SNS 알림 토픽 (key-sns 암호화) ----
resource "aws_sns_topic" "security_alerts" {
  name              = "security-flowlogs-alerts"
  kms_master_key_id = data.aws_kms_key.key_sns.arn
  tags              = { Name = "security-flowlogs-alerts" }
}

# Slack 구독: AWS Chatbot 방식이면 Chatbot 쪽에서 이 토픽 ARN을 구독함(여기 코드 불필요).
# 임시 이메일 알림이 필요하면 아래 주석 해제:
# resource "aws_sns_topic_subscription" "email" {
#   topic_arn = aws_sns_topic.security_alerts.arn
#   protocol  = "email"
#   endpoint  = "security@example.com"
# }

# ---- 알람 1: vpc1 DB포트 probe ----
resource "aws_cloudwatch_metric_alarm" "db_port_probe_vpc1" {
  alarm_name          = "flowlogs-dbport-probe-vpc1"
  namespace           = "Security/FlowLogs/vpc1"
  metric_name         = "DbPortProbeCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 5 # baseline 관측 후 튜닝
  treat_missing_data  = "notBreaching"
  alarm_description   = "vpc1 외부→DB포트 REJECT 5분 누적 5회+ (포트 probe 의심)"
  alarm_actions       = [aws_sns_topic.security_alerts.arn]
}

# ---- 알람 2: vpc1 REJECT 버스트 ----
# 진짜 포트스캔(단일 출발지 다수 포트)은 metric filter로 탐지 불가
# (distinct count/group-by 불가 → Contributor Insights 또는 MAS Agent 영역)
# 여기선 REJECT 총량 급증으로 근사
resource "aws_cloudwatch_metric_alarm" "reject_burst_vpc1" {
  alarm_name          = "flowlogs-reject-burst-vpc1"
  namespace           = "Security/FlowLogs/vpc1"
  metric_name         = "RejectCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 500 # baseline 관측 후 튜닝
  treat_missing_data  = "notBreaching"
  alarm_description   = "vpc1 REJECT 5분 누적 500 초과 (스캔/공격 급증 의심)"
  alarm_actions       = [aws_sns_topic.security_alerts.arn]
}
