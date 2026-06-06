# =============================================
# MFA 강제 정책
# MFA 없이 로그인하면 아무것도 못하게 차단
# 단, MFA 등록 행동만큼은 허용 (처음 로그인 시 등록해야 하니까)
# =============================================
resource "aws_iam_policy" "require_mfa" {
  name = "require-mfa"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "DenyWithoutMFA"
      Effect = "Deny"
      # NotAction = 여기 나열된 것 제외하고 전부 차단
      NotAction = [
        "iam:CreateVirtualMFADevice", # MFA 기기 생성
        "iam:EnableMFADevice",        # MFA 활성화
        "iam:GetUser",                # 내 계정 정보 조회
        "iam:ListMFADevices",         # MFA 목록 조회
        "sts:GetSessionToken"         # 세션 토큰 발급
      ]
      Resource = "*"
      Condition = {
        BoolIfExists = {
          # MFA 인증 안 된 상태일 때만 이 차단 적용
          "aws:MultiFactorAuthPresent" = "false"
        }
      }
    }]
  })
}

# 전체 그룹에 MFA 정책 적용
resource "aws_iam_group_policy_attachment" "mfa_infra" {
  group      = aws_iam_group.infra_admin.name
  policy_arn = aws_iam_policy.require_mfa.arn
}

resource "aws_iam_group_policy_attachment" "mfa_security" {
  group      = aws_iam_group.security_engineers.name
  policy_arn = aws_iam_policy.require_mfa.arn
}

resource "aws_iam_group_policy_attachment" "mfa_platform" {
  group      = aws_iam_group.platform_engineers.name
  policy_arn = aws_iam_policy.require_mfa.arn
}

resource "aws_iam_group_policy_attachment" "mfa_sre" {
  group      = aws_iam_group.sre_engineers.name
  policy_arn = aws_iam_policy.require_mfa.arn
}

# mas 그룹 MFA 강제 적용
resource "aws_iam_group_policy_attachment" "mfa_mas" {
  group      = aws_iam_group.mas.name
  policy_arn = aws_iam_policy.require_mfa.arn
}

# =============================================
# 비밀번호 정책 (#37)
# 이 코드 하나로 AWS 계정 전체 비밀번호 규칙 적용
# =============================================
resource "aws_iam_account_password_policy" "strict" {
  minimum_password_length      = 14   # 최소 14자
  require_uppercase_characters = true # 대문자 필수
  require_lowercase_characters = true # 소문자 필수
  require_numbers              = true # 숫자 필수
  require_symbols              = true # 특수문자 필수
  max_password_age             = 90   # 90일마다 변경
  password_reuse_prevention    = 24   # 이전 24개 재사용 금지
}