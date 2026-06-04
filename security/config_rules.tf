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
