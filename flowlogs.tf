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
# 차원 없음(스칼라) → 커스텀 메트릭 무료 10개 내. baseline·비용 모니터링용
resource "aws_cloudwatch_log_metric_filter" "reject_count" {
  for_each       = local.flowlog_vpcs
  name           = "flowlogs-reject-count-${each.key}"
  log_group_name = aws_cloudwatch_log_group.flowlogs[each.key].name
  # action=REJECT 만 매칭 — NODATA/SKIPDATA 레코드는 action 자리가 "-" 라 제외됨
  pattern = "[version, account_id, interface_id, srcaddr, dstaddr, srcport, dstport, protocol, packets, bytes, start, end, action=REJECT, log_status]"

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

# =====================================================================
# VPC Flow Logs → S3 (ALL 트래픽, Parquet)
#   대상:      vpc1(globalservice) + vpc2(ops)
#   목적:      Hubble 도입 전 전체 트래픽 용량·비용 측정
#   on/off:    enable_flowlog_s3_archive 변수 (기본 false)
#   apply 순서: kms/ 먼저 apply → 루트 apply → 변수 true
# =====================================================================

locals {
  flowlog_s3_vpcs = {
    vpc1 = module.vpc1.vpc_id # globalservice (대국민 서비스망)
    vpc2 = module.vpc2.vpc_id # ops (내부 운영망)
  }
}

# ---- S3 버킷 (Object Lock 활성화 — 생성 후 변경 불가) ----
resource "aws_s3_bucket" "flowlogs_archive" {
  count               = var.enable_flowlog_s3_archive ? 1 : 0
  bucket              = "financial-flowlogs-archive-${data.aws_caller_identity.current.account_id}"
  object_lock_enabled = true
  # GOVERNANCE bypass 권한(s3:BypassGovernanceRetention)으로 terraform destroy 가능
  force_destroy = true

  tags = {
    Name    = "financial-flowlogs-archive"
    Purpose = "flowlog-volume-measurement"
  }
}

# ---- 버저닝 (Object Lock 필수 조건) ----
resource "aws_s3_bucket_versioning" "flowlogs_archive" {
  count  = var.enable_flowlog_s3_archive ? 1 : 0
  bucket = aws_s3_bucket.flowlogs_archive[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

# ---- Object Ownership: ACL 비활성화, 버킷 정책으로만 접근 제어 ----
resource "aws_s3_bucket_ownership_controls" "flowlogs_archive" {
  count  = var.enable_flowlog_s3_archive ? 1 : 0
  bucket = aws_s3_bucket.flowlogs_archive[0].id
  rule { object_ownership = "BucketOwnerEnforced" }
}

# ---- 퍼블릭 차단 ----
resource "aws_s3_bucket_public_access_block" "flowlogs_archive" {
  count  = var.enable_flowlog_s3_archive ? 1 : 0
  bucket = aws_s3_bucket.flowlogs_archive[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---- SSE-KMS (key-s3, 런타임 alias 조회) ----
resource "aws_s3_bucket_server_side_encryption_configuration" "flowlogs_archive" {
  count  = var.enable_flowlog_s3_archive ? 1 : 0
  bucket = aws_s3_bucket.flowlogs_archive[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = data.aws_kms_key.key_s3.arn
    }
    bucket_key_enabled = true # KMS API 호출 횟수 감소 → 비용 절감
  }
}

# ---- Object Lock: GOVERNANCE 7일 ----
# COMPLIANCE 아님 — GOVERNANCE + s3:BypassGovernanceRetention 권한으로 terraform destroy 가능
# COMPLIANCE로 변경 시 retention 만료 전 버킷 삭제 불가 → 주기적 재구축 워크플로우 파괴
resource "aws_s3_bucket_object_lock_configuration" "flowlogs_archive" {
  count  = var.enable_flowlog_s3_archive ? 1 : 0
  bucket = aws_s3_bucket.flowlogs_archive[0].id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.flowlogs_archive]
}

# ---- Lifecycle: 90일 → Glacier Deep Archive → 7년 만료 ----
resource "aws_s3_bucket_lifecycle_configuration" "flowlogs_archive" {
  count  = var.enable_flowlog_s3_archive ? 1 : 0
  bucket = aws_s3_bucket.flowlogs_archive[0].id

  rule {
    id     = "flowlogs-tiering"
    status = "Enabled"
    filter { prefix = "" }

    transition {
      days          = 90
      storage_class = "DEEP_ARCHIVE"
    }

    expiration {
      days = 2555 # 7년 (365×7)
    }

    noncurrent_version_expiration {
      noncurrent_days = 8 # Object Lock 7일 retention 만료 이후 정리
    }
  }

  depends_on = [aws_s3_bucket_versioning.flowlogs_archive]
}

# ---- 버킷 정책: delivery.logs.amazonaws.com 허용 ----
# SourceAccount + SourceArn 두 조건 모두 — confused-deputy 이중 방어
# AWSLogs/* : hive 파티션(aws-account-id=..) · 기본(account-id/..) 경로 모두 커버
resource "aws_s3_bucket_policy" "flowlogs_archive" {
  count  = var.enable_flowlog_s3_archive ? 1 : 0
  bucket = aws_s3_bucket.flowlogs_archive[0].id

  depends_on = [aws_s3_bucket_public_access_block.flowlogs_archive]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowFlowLogsDelivery"
        Effect = "Allow"
        Principal = {
          Service = "delivery.logs.amazonaws.com"
        }
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.flowlogs_archive[0].arn}/AWSLogs/*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      },
      {
        # delivery 서비스가 쓰기 전 버킷 ACL·존재 확인 — BucketOwnerEnforced여도 호출 자체는 발생
        # Resource는 버킷 루트 ARN (ACL은 버킷 속성이라 /AWSLogs/* 붙이면 안 됨)
        Sid    = "AWSLogDeliveryAclCheck"
        Effect = "Allow"
        Principal = {
          Service = "delivery.logs.amazonaws.com"
        }
        Action   = ["s3:GetBucketAcl", "s3:ListBucket"]
        Resource = aws_s3_bucket.flowlogs_archive[0].arn
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      }
    ]
  })
}

# ---- Flow Logs → S3 (ALL 트래픽, Parquet, 10분 집계) ----
# 기존 aws_flow_log.this (REJECT-only, CloudWatch) 는 무수정
resource "aws_flow_log" "s3_archive" {
  for_each = var.enable_flowlog_s3_archive ? local.flowlog_s3_vpcs : {}

  vpc_id                   = each.value
  traffic_type             = "ALL"
  log_destination_type     = "s3"
  log_destination          = aws_s3_bucket.flowlogs_archive[0].arn
  max_aggregation_interval = 600 # 10분 집계 — 60초 대비 비용 1/10

  destination_options {
    file_format                = "parquet"
    hive_compatible_partitions = true
    per_hour_partition         = true
  }
  depends_on = [
    aws_s3_bucket_policy.flowlogs_archive,
    aws_s3_bucket_server_side_encryption_configuration.flowlogs_archive,
  ]

  tags = {
    Name    = "flowlog-s3-${each.key}"
    Purpose = "flowlog-volume-measurement"
  }
}
