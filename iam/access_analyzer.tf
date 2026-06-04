# =============================================
# IAM Access Analyzer
#
# 두 가지 분석기를 병행 운영:
#   1. external-access-analyzer (ACCOUNT)
#      - S3, IAM Role, KMS 등 리소스 정책에서 외부/공개 접근 탐지
#      - 무료 (AWS 기본 제공)
#
#   2. unused-access-analyzer (ACCOUNT_UNUSED_ACCESS)
#      - IAM User/Role 중 90일간 미사용 권한 탐지
#      - 최소 권한 원칙 적용 근거 데이터 제공
#      - 유료: IAM Role/User 수에 따라 소과금
# =============================================

# =============================================
# 1. 외부 접근 분석기 (무료)
#
# 리소스 기반 정책(S3 버킷, KMS, IAM Role Trust Policy 등)에서
# 계정 외부에 접근을 허용하는 설정을 자동 탐지
# =============================================
resource "aws_accessanalyzer_analyzer" "external_access" {
  analyzer_name = "external-access-analyzer"
  type          = "ACCOUNT"

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "IAM"
    Environment = "all"
  }
}

# =============================================
# 2. 미사용 접근 분석기 (유료)
#
# unused_access_age = 90: 90일간 미사용된 권한을 잠재적 위험으로 분류 -> 우리는 7일로 하자
# 금융권 최소 권한 원칙(Least Privilege) 준수 점검에 활용
# =============================================
resource "aws_accessanalyzer_analyzer" "unused_access" {
  analyzer_name = "unused-access-analyzer"
  type          = "ACCOUNT_UNUSED_ACCESS"

  configuration {
    unused_access {
      unused_access_age = 7
    }
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "IAM"
    Environment = "all"
  }
}
