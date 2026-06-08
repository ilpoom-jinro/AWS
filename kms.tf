# =============================================
# RDS용 CMK (Customer Managed Key)
# key-rds-ops           → VPC2 (내부 운영망) RDS 전용
# key-rds-globalservice → VPC1 (서비스망) RDS 전용
#
# 금융권 Key Policy 구조
#   - root                  : 잠금 방지용 (실제 사용 안 함)
#   - kms_admin Role        : 일반 관리 전용 (생성/수정/로테이션)
#   - kms_breakglass Role   : 삭제/비활성화 전용 (MFA 필수)
#   - rds.amazonaws.com     : 암호화/복호화만
#   - Cross-account         : 명시적 Deny
#   - CloudTrail 비활성화   : 명시적 Deny
#
# RDS 생성 시 주의사항 (#34)
#   storage_encrypted = true
#   kms_key_id        = output ARN 참조
#   생성 후 변경 불가 → 처음부터 반드시 설정
# =============================================

# =============================================
# key-rds-ops (VPC2 내부 운영망 RDS)
# =============================================
resource "aws_kms_key" "key_rds_ops" {
  description             = "RDS CMK for financial-vpc2-ops"
  enable_key_rotation     = true # 1년마다 자동 키 재료 교체 (금융권 의무)
  deletion_window_in_days = 30   # 삭제 예약 후 30일 대기 (최대값, 실수 방지)

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # root: 잠금 방지용
        # KMS 키 정책이 잘못 설정돼도 root로 복구 가능하게 유지
        Sid    = "EnableRootAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        # kms_admin Role: 일반 관리 작업만 허용
        # 삭제/비활성화는 포함하지 않음
        # iam 모듈과 루트 모듈이 분리되어 있어서 ARN 문자열로 직접 참조
        Sid    = "AllowKMSAdminRole"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/financial-kms-admin-role"
        }
        Action = [
          "kms:CreateKey",
          "kms:DescribeKey",
          "kms:EnableKeyRotation",
          "kms:DisableKeyRotation",
          "kms:GetKeyRotationStatus",
          "kms:ListKeys",
          "kms:ListAliases",
          "kms:PutKeyPolicy",
          "kms:GetKeyPolicy",
          "kms:UpdateKeyDescription",
          "kms:CreateAlias",
          "kms:UpdateAlias",
          "kms:DeleteAlias",
          "kms:EnableKey",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:ListResourceTags"
        ]
        Resource = "*"
      },
      {
        # kms_breakglass Role: 삭제/비활성화만 허용
        # MFA 인증된 세션에서만 사용 가능 (roles.tf에서 Assume 조건으로 강제)
        # iam 모듈과 루트 모듈이 분리되어 있어서 ARN 문자열로 직접 참조
        Sid    = "AllowKMSBreakGlassRole"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/financial-kms-breakglass-role"
        }
        Action = [
          "kms:ScheduleKeyDeletion", # 키 삭제 예약
          "kms:CancelKeyDeletion",   # 키 삭제 취소
          "kms:DisableKey",          # 키 비활성화
          "kms:DescribeKey",         # 키 상태 확인
          "kms:ListKeys",
          "kms:ListAliases"
        ]
        Resource = "*"
      },
      {
        # rds.amazonaws.com: 암호화/복호화만 허용
        # RDS가 DEK 생성 및 복호화할 때 사용
        # 관리 권한은 없음 (최소 권한 원칙)
        Sid    = "AllowRDSService"
        Effect = "Allow"
        Principal = {
          Service = "rds.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",          # DEK 복호화
          "kms:GenerateDataKey*", # DEK 생성
          "kms:CreateGrant",      # RDS 내부 권한 위임
          "kms:DescribeKey"       # 키 정보 조회
        ]
        Resource = "*"
      },
      {
        # 금융권 필수: Cross-account 키 공유 차단
        # 다른 AWS 계정에서 이 키 사용 완전 차단
        Sid    = "DenyCrossAccount"
        Effect = "Deny"
        Principal = {
          AWS = "*"
        }
        Action   = "kms:*"
        Resource = "*"
        Condition = {
          StringNotEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
      {
        # 금융권 필수: MFA 없는 키 삭제/비활성화 차단
        # BreakGlass Role도 MFA 없으면 차단 (이중 방어)
        Sid    = "DenyWithoutMFA"
        Effect = "Deny"
        Principal = {
          AWS = "*"
        }
        Action = [
          "kms:DisableKey",         # 키 비활성화
          "kms:ScheduleKeyDeletion" # 키 삭제 예약
        ]
        Resource = "*"
        Condition = {
          BoolIfExists = {
            # MFA 없는 세션에서 삭제/비활성화 시도 차단
            "aws:MultiFactorAuthPresent" = "false"
          }
        }
      }
    ]
  })

  # module.iam이 먼저 완료돼야 Role ARN이 유효해짐 (병렬 실행 방지)
  depends_on = [module.iam]

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "RDS"
    Environment = "ops"
  }
}

# alias: 사람이 읽기 쉬운 키 이름표
# rds.tf에서 alias/key-rds-ops 로 참조 가능
resource "aws_kms_alias" "key_rds_ops" {
  name          = "alias/key-rds-ops"
  target_key_id = aws_kms_key.key_rds_ops.key_id
}

# =============================================
# key-rds-globalservice (VPC1 서비스망 RDS)
# ops와 동일한 정책 구조, 환경만 다름
# =============================================
resource "aws_kms_key" "key_rds_globalservice" {
  description             = "RDS CMK for financial-vpc1-service"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableRootAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowKMSAdminRole"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/financial-kms-admin-role"
        }
        Action = [
          "kms:CreateKey",
          "kms:DescribeKey",
          "kms:EnableKeyRotation",
          "kms:DisableKeyRotation",
          "kms:GetKeyRotationStatus",
          "kms:ListKeys",
          "kms:ListAliases",
          "kms:PutKeyPolicy",
          "kms:GetKeyPolicy",
          "kms:UpdateKeyDescription",
          "kms:CreateAlias",
          "kms:UpdateAlias",
          "kms:DeleteAlias",
          "kms:EnableKey",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:ListResourceTags"
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowKMSBreakGlassRole"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/financial-kms-breakglass-role"
        }
        Action = [
          "kms:ScheduleKeyDeletion",
          "kms:CancelKeyDeletion",
          "kms:DisableKey",
          "kms:DescribeKey",
          "kms:ListKeys",
          "kms:ListAliases"
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowRDSService"
        Effect = "Allow"
        Principal = {
          Service = "rds.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey*",
          "kms:CreateGrant",
          "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        Sid    = "DenyCrossAccount"
        Effect = "Deny"
        Principal = {
          AWS = "*"
        }
        Action   = "kms:*"
        Resource = "*"
        Condition = {
          StringNotEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
      {
        Sid    = "DenyWithoutMFA"
        Effect = "Deny"
        Principal = {
          AWS = "*"
        }
        Action = [
          "kms:DisableKey",
          "kms:ScheduleKeyDeletion"
        ]
        Resource = "*"
        Condition = {
          BoolIfExists = {
            "aws:MultiFactorAuthPresent" = "false"
          }
        }
      }
    ]
  })

  # module.iam이 먼저 완료돼야 Role ARN이 유효해짐 (병렬 실행 방지)
  depends_on = [module.iam]

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "RDS"
    Environment = "globalservice"
  }
}

resource "aws_kms_alias" "key_rds_globalservice" {
  name          = "alias/key-rds-globalservice"
  target_key_id = aws_kms_key.key_rds_globalservice.key_id
}

# KMS 키 생성 후 AWS 내부 전파 대기
# 키 생성 직후 RDS가 바로 사용하면 inaccessible-encryption-credentials 발생
resource "time_sleep" "kms_rds_propagation" {
  depends_on = [
    aws_kms_key.key_rds_ops,
    aws_kms_key.key_rds_globalservice
  ]
  create_duration = "15s"
}
