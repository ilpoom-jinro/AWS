# =============================================
# KMS 관련 IAM Role 2개
#
# 1. financial-kms-admin-role (일반 관리)
#    - 키 생성, 수정, 로테이션 등 일상적인 관리 작업
#    - dev_mode = true  → 전체 팀원 Assume 가능
#    - dev_mode = false → security 유저만 Assume 가능
#
# 2. financial-kms-breakglass-role (긴급 전용)
#    - 키 삭제, 비활성화 등 고위험 작업
#    - MFA 인증된 세션에서만 Assume 가능 (dev_mode 무관)
#    - 금융권 필수: 키 삭제는 MFA + BreakGlass Role만 가능
#
# data "aws_caller_identity" "current" 는
# app-manifest-updater.tf에 선언되어 있어서 여기서 생략
# =============================================

# =============================================
# 1. KMS 일반 관리 Role
# =============================================
resource "aws_iam_role" "kms_admin" {
  name        = "financial-kms-admin-role"
  description = "KMS 키 일반 관리 전용 Role (보안팀 전용)"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowAssumeRole"
      Effect = "Allow"
      Principal = {
        AWS = var.dev_mode ? [
          # dev_mode = true → 전체 팀원 Assume 가능 (개발 중)
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/security",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/infra",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/platform",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/sre"
        ] : [
          # dev_mode = false → security 유저만 (운영)
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/security"
        ]
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

resource "aws_iam_policy" "kms_admin_policy" {
  name        = "financial-kms-admin-policy"
  description = "KMS 키 일반 관리 정책 (생성/수정/로테이션, 삭제 제외)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "KMSAdminActions"
        Effect = "Allow"
        Action = [
          "kms:CreateKey",            # CMK 생성
          "kms:DescribeKey",          # 키 정보 조회
          "kms:EnableKeyRotation",    # 자동 로테이션 활성화
          "kms:DisableKeyRotation",   # 자동 로테이션 비활성화
          "kms:GetKeyRotationStatus", # 로테이션 상태 조회
          "kms:ListKeys",             # 전체 키 목록 조회
          "kms:ListAliases",          # 전체 alias 목록 조회
          "kms:PutKeyPolicy",         # 키 정책 설정
          "kms:GetKeyPolicy",         # 키 정책 조회
          "kms:UpdateKeyDescription", # 키 설명 수정
          "kms:CreateAlias",          # alias 생성
          "kms:UpdateAlias",          # alias 수정
          "kms:DeleteAlias",          # alias 삭제
          "kms:EnableKey",            # 키 활성화
          "kms:TagResource",          # 키 태그 추가
          "kms:UntagResource",        # 키 태그 제거
          "kms:ListResourceTags"      # 키 태그 조회
        ]
        Resource = "*"
      },
      {
        # 금융권 필수: Cross-account 키 공유 명시적 차단
        # 다른 AWS 계정에서 이 키 사용 불가
        Sid    = "DenyCrossAccount"
        Effect = "Deny"
        Action = "kms:*"
        Resource = "*"
        Condition = {
          StringNotEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })

  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "security"
  }
}

resource "aws_iam_role_policy_attachment" "kms_admin" {
  role       = aws_iam_role.kms_admin.name
  policy_arn = aws_iam_policy.kms_admin_policy.arn
}

# =============================================
# 2. KMS BreakGlass Role (긴급 전용)
# 키 삭제/비활성화 등 고위험 작업 전용
# MFA 조건은 dev_mode 무관하게 항상 강제
# → 개발 중에도 키 삭제는 MFA 필수
# =============================================
resource "aws_iam_role" "kms_breakglass" {
  name        = "financial-kms-breakglass-role"
  description = "KMS 키 삭제·비활성화 전용 긴급 Role (MFA 필수)"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowAssumeRoleWithMFA"
      Effect = "Allow"
      Principal = {
        AWS = var.dev_mode ? [
          # dev_mode = true → 전체 팀원 Assume 가능 (단, MFA 필수는 유지)
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/security",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/infra",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/platform",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/sre"
        ] : [
          # dev_mode = false → security 유저만
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/security"
        ]
      }
      Action = "sts:AssumeRole"
      Condition = {
        Bool = {
          # dev_mode 무관하게 항상 MFA 필수
          "aws:MultiFactorAuthPresent" = "true"
        }
        NumericLessThan = {
          # MFA 인증 후 1시간 이내에서만 Assume 가능
          "aws:MultiFactorAuthAge" = "3600"
        }
      }
    }]
  })

  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "security"
  }
}

resource "aws_iam_policy" "kms_breakglass_policy" {
  name        = "financial-kms-breakglass-policy"
  description = "KMS 키 삭제·비활성화 전용 정책 (BreakGlass Role에 연결)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "KMSBreakGlassActions"
        Effect = "Allow"
        Action = [
          "kms:ScheduleKeyDeletion", # 키 삭제 예약 (최소 7일 대기)
          "kms:CancelKeyDeletion",   # 키 삭제 취소
          "kms:DisableKey",          # 키 비활성화 (긴급 차단)
          "kms:DescribeKey",         # 키 상태 확인
          "kms:ListKeys",            # 키 목록 조회
          "kms:ListAliases"          # alias 목록 조회
        ]
        Resource = "*"
      },
      {
        # Cross-account 차단
        Sid    = "DenyCrossAccount"
        Effect = "Deny"
        Action = "kms:*"
        Resource = "*"
        Condition = {
          StringNotEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })

  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "security"
  }
}

resource "aws_iam_role_policy_attachment" "kms_breakglass" {
  role       = aws_iam_role.kms_breakglass.name
  policy_arn = aws_iam_policy.kms_breakglass_policy.arn
}