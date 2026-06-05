# =============================================
# AWS Config - IAM 리소스 변경 이력 기록
#
# 금융권 필수: IAM 변경 사항 전수 감사
#   - 기록 대상: IAM User, Group, Role, Policy
#   - all_supported = false → IAM 리소스만 선택 기록 (비용 최소화)
#   - include_global_resource_types = true → IAM은 글로벌 리소스
#   - Config 스냅샷은 S3에 저장 (퍼블릭 접근 차단)
# =============================================

# 계정 ID 조회 (S3 버킷명, IAM Role ARN 구성에 사용)
data "aws_caller_identity" "current" {}

# =============================================
# S3 버킷 - Config 스냅샷 저장
# 버킷명에 계정 ID 포함 → 전역 고유성 보장
# =============================================
resource "aws_s3_bucket" "config_snapshot" {
  bucket = "financial-config-snapshot-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "Config"
    Environment = "all"
  }
}

# 퍼블릭 접근 완전 차단 (금융권 필수)
resource "aws_s3_bucket_public_access_block" "config_snapshot" {
  bucket = aws_s3_bucket.config_snapshot.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Config 서비스가 S3에 스냅샷을 쓸 수 있도록 버킷 정책 설정
resource "aws_s3_bucket_policy" "config_snapshot" {
  bucket = aws_s3_bucket.config_snapshot.id

  # 퍼블릭 접근 차단이 먼저 적용된 후 버킷 정책을 붙여야 함
  depends_on = [aws_s3_bucket_public_access_block.config_snapshot]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Config가 버킷 ACL을 확인한 뒤 스냅샷을 저장하는 구조
        # GetBucketAcl 없으면 Config가 PutObject 전 권한 검증 실패
        Sid    = "AWSConfigBucketPermissionsCheck"
        Effect = "Allow"
        Principal = {
          Service = "config.amazonaws.com"
        }
        Action   = "s3:GetBucketAcl"
        Resource = aws_s3_bucket.config_snapshot.arn
      },
      {
        # Config 스냅샷 파일 업로드 허용
        # bucket-owner-full-control 조건: 버킷 소유자가 항상 객체를 제어할 수 있게 강제
        Sid    = "AWSConfigBucketDelivery"
        Effect = "Allow"
        Principal = {
          Service = "config.amazonaws.com"
        }
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.config_snapshot.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/Config/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl" = "bucket-owner-full-control"
          }
        }
      }
    ]
  })
}

# =============================================
# IAM Role - Config 서비스 전용
# Config가 IAM 리소스를 읽고 S3에 전달하는 데 필요
# =============================================
resource "aws_iam_role" "config_recorder" {
  name        = "financial-config-recorder-role"
  description = "AWS Config recorder role for IAM resource auditing"

  # config.amazonaws.com 서비스만 이 Role을 Assume 가능
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowConfigService"
      Effect = "Allow"
      Principal = {
        Service = "config.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "security"
  }
}

# AWS 관리형 정책: Config가 리소스를 읽고 S3/SNS에 전달하는 권한 포함
resource "aws_iam_role_policy_attachment" "config_recorder" {
  role       = aws_iam_role.config_recorder.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWS_ConfigRole"
}

# S3 버킷에 스냅샷을 직접 쓰는 권한
# AWS_ConfigRole에 특정 버킷 PutObject가 포함되지 않아 별도 추가
resource "aws_iam_role_policy" "config_s3_delivery" {
  name = "financial-config-s3-delivery-policy"
  role = aws_iam_role.config_recorder.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowS3Delivery"
      Effect = "Allow"
      Action = [
        "s3:PutObject"
      ]
      Resource = "${aws_s3_bucket.config_snapshot.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/Config/*"
      Condition = {
        StringEquals = {
          "s3:x-amz-acl" = "bucket-owner-full-control"
        }
      }
    }]
  })
}

# =============================================
# aws_config_configuration_recorder
# IAM 리소스만 선택적으로 기록 (all_supported = false)
# include_global_resource_types = true → IAM은 글로벌 서비스
# =============================================
resource "aws_config_configuration_recorder" "main" {
  name     = "financial-config-recorder"
  role_arn = aws_iam_role.config_recorder.arn

  recording_group {
    all_supported                 = false # 전체 리소스 기록 비활성화 (비용 최소화)
    include_global_resource_types = false # all_supported = false일 때 true 불가, IAM은 resource_types에 명시

    resource_types = [
      "AWS::IAM::User",   # IAM 사용자
      "AWS::IAM::Group",  # IAM 그룹
      "AWS::IAM::Role",   # IAM 역할
      "AWS::IAM::Policy", # IAM 정책
    ]
  }
}

# =============================================
# aws_config_delivery_channel
# Config 스냅샷을 S3 버킷으로 전달
# 레코더보다 먼저 존재해야 레코더 status 활성화 가능
# =============================================
resource "aws_config_delivery_channel" "main" {
  name           = "financial-config-delivery-channel"
  s3_bucket_name = aws_s3_bucket.config_snapshot.bucket

  # 1시간마다 S3로 스냅샷 자동 전달
  snapshot_delivery_properties {
    delivery_frequency = "One_Hour"
  }

  # 레코더가 먼저 생성돼야 전달 채널을 만들 수 있음
  depends_on = [aws_config_configuration_recorder.main]
}

# =============================================
# aws_config_configuration_recorder_status
# 레코더 생성 + 전달 채널 준비 후 recording 활성화
# =============================================
resource "aws_config_configuration_recorder_status" "main" {
  name       = aws_config_configuration_recorder.main.name
  is_enabled = true # 기록 활성화

  # 전달 채널이 없으면 레코더를 활성화할 수 없음
  depends_on = [aws_config_delivery_channel.main]
}
