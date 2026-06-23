# =============================================
# AWS Config Rules - IAM 보안 규칙
#
# 금융권 필수: IAM Access Key 90일 주기 강제 로테이션
#   - maxAccessKeyAge = 90일 초과 시 NON_COMPLIANT 표시
#   - Config 레코더가 활성화돼야 규칙 평가 가능
# =============================================

# =============================================
# access-keys-rotated
# IAM Access Key가 90일 이내에 로테이션됐는지 검사
# NON_COMPLIANT 조건: 마지막 로테이션이 90일 초과
# =============================================
resource "aws_config_config_rule" "access_keys_rotated" {
  name        = "access-keys-rotated"
  description = "IAM Access Key가 90일 이내에 로테이션됐는지 검사 (금융권 의무)"

  source {
    owner             = "AWS"                 # AWS 관리형 규칙
    source_identifier = "ACCESS_KEYS_ROTATED" # AWS 관리형 규칙 식별자
  }

  # 최대 키 유효 기간: 90일 (금융권 기준)
  input_parameters = jsonencode({
    maxAccessKeyAge = "90"
  })

  # Config 레코더가 활성화된 후에만 규칙 생성 및 평가 가능
  depends_on = [aws_config_configuration_recorder_status.main]

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "Config"
    Environment = "all"
  }
}

# =============================================
# ec2-ebs-encryption-by-default (#32)
# 계정+리전 EBS 기본 암호화가 켜져 있는지 검사
#   - NON_COMPLIANT: 기본 암호화가 꺼져 있을 때
#   - 트리거: Periodic (계정 설정만 점검) → 리소스 기록 불필요 → 비용 거의 0
#   - EBS 기본 암호화는 #30(kms/ebs.tf)에서 ON. 이 룰은 그 설정이 꺼지면 탐지하는 드리프트 감지
# =============================================
resource "aws_config_config_rule" "ec2_ebs_encryption_by_default" {
  name        = "ec2-ebs-encryption-by-default"
  description = "EBS 계정 기본 암호화 활성화 여부 검사 — #30 설정 드리프트 감지 (#32)"

  source {
    owner             = "AWS"                           # AWS 관리형 규칙
    source_identifier = "EC2_EBS_ENCRYPTION_BY_DEFAULT" # 관리형 규칙 식별자
  }

  # periodic 룰 — 24시간마다 계정 설정 점검
  maximum_execution_frequency = "TwentyFour_Hours"

  # Config가 활성화된 후에만 룰 생성/평가 가능 (기존 룰과 동일 패턴)
  depends_on = [aws_config_configuration_recorder_status.main]

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "Config"
    Environment = "all"
  }
}
