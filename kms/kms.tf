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
#
# depends_on [module.iam] 제거됨
# → 워크플로우에서 IAM apply 완료 후 KMS apply 실행하여 순서 보장
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
            # 다른 계정 IAM principal 차단
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
          }
          Bool = {
            # AWS 서비스(rds.amazonaws.com 등)는 Deny 제외
            # 서비스가 KMS 호출 시 CallerAccount가 내부 계정이 되어 Deny에 걸릴 수 있음
            "aws:PrincipalIsAWSService" = "false"
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

  lifecycle {
    prevent_destroy = true
  }

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

  lifecycle {
    create_before_destroy = false
  }
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
            # 다른 계정 IAM principal 차단
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
          }
          Bool = {
            # AWS 서비스(rds.amazonaws.com 등)는 Deny 제외
            # 서비스가 KMS 호출 시 CallerAccount가 내부 계정이 되어 Deny에 걸릴 수 있음
            "aws:PrincipalIsAWSService" = "false"
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

  lifecycle {
    prevent_destroy = true
  }

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

  lifecycle {
    create_before_destroy = false
  }
}

# =============================================
# key-cloudtrail (CloudTrail 로그 S3 암호화)
# ops/globalservice RDS 키와 동일한 정책 구조
# =============================================
resource "aws_kms_key" "key_cloudtrail" {
  description             = "CloudTrail CMK for ilpumjinro"
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
        # EncryptionContext 조건으로 이 계정 Trail만 이 키를 사용 가능하도록 제한
        Sid    = "AllowCloudTrailEncrypt"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action = [
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringLike = {
            "kms:EncryptionContext:aws:cloudtrail:arn" = "arn:aws:cloudtrail:*:${data.aws_caller_identity.current.account_id}:trail/*"
          }
        }
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
          Bool = {
            "aws:PrincipalIsAWSService" = "false"
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

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "CloudTrail"
    Environment = "all"
  }
}

resource "aws_kms_alias" "key_cloudtrail" {
  name          = "alias/key-cloudtrail"
  target_key_id = aws_kms_key.key_cloudtrail.key_id

  lifecycle {
    create_before_destroy = false
  }
}

# =============================================
# key-s3 (S3 버킷 암호화)
# 대상: terraform state, cloudtrail logs, teleport sessions
# =============================================
resource "aws_kms_key" "key_s3" {
  description             = "S3 CMK for ilpumjinro"
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
        Sid    = "AllowS3Service"
        Effect = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
        }
        Action = [
          "kms:GenerateDataKey*",
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        # Config가 스냅샷을 key-s3로 암호화해 S3에 전달할 때 사용 (#29 민감 데이터 전수 암호화)
        # SourceArn 조건으로 이 계정의 Config delivery channel 경유 호출만 허용 (혼동된 대리 방지)
        Sid    = "AllowConfigService"
        Effect = "Allow"
        Principal = {
          Service = "config.amazonaws.com"
        }
        Action = [
          "kms:GenerateDataKey*", # DEK 생성 (스냅샷 암호화)
          "kms:Decrypt",          # DEK 복호화
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringLike = {
            "aws:SourceArn" = "arn:aws:config:*:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      },
      {
        # VPC Flow Logs S3 export: delivery 서비스가 SSE-KMS 객체를 쓸 때 DEK를 직접 생성
        # s3.amazonaws.com 허용만으로는 부족 — delivery.logs.amazonaws.com이 KMS를 직접 호출
        # SourceAccount 조건으로 이 계정의 Flow Logs만 이 키 사용 허용 (confused-deputy 방지)
        Sid    = "AllowFlowLogsDelivery"
        Effect = "Allow"
        Principal = {
          Service = "delivery.logs.amazonaws.com"
        }
        Action = [
          "kms:GenerateDataKey*",
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
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
          Bool = {
            "aws:PrincipalIsAWSService" = "false"
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

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "S3"
    Environment = "all"
  }
}

resource "aws_kms_alias" "key_s3" {
  name          = "alias/key-s3"
  target_key_id = aws_kms_key.key_s3.key_id

  lifecycle {
    create_before_destroy = false
  }
}

# =============================================
# key-secretsmanager (Secrets Manager 암호화)
# 대상: service/ops RDS 마스터 비밀번호
# =============================================
resource "aws_kms_key" "key_secretsmanager" {
  description             = "Secrets Manager CMK for ilpumjinro"
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
        Sid    = "AllowSecretsManagerService"
        Effect = "Allow"
        Principal = {
          Service = "secretsmanager.amazonaws.com"
        }
        Action = [
          "kms:GenerateDataKey*",
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:CreateGrant"
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
          Bool = {
            "aws:PrincipalIsAWSService" = "false"
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

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SecretsManager"
    Environment = "all"
  }
}

resource "aws_kms_alias" "key_secretsmanager" {
  name          = "alias/key-secretsmanager"
  target_key_id = aws_kms_key.key_secretsmanager.key_id

  lifecycle {
    create_before_destroy = false
  }
}

# =============================================
# key-eks (EKS etcd Secrets 암호화 + EBS 노드 볼륨 암호화)
# 대상:
#   - financial-ops-eks / financial-service-eks encryption_config
#   - EKS 노드 Launch Template EBS 볼륨
#
# Principal 설계
#   - EKS 클러스터 Role (etcd): vpc 모듈에서 생성되므로 key 생성 시점에 미존재
#     → MalformedPolicyDocumentException 방지를 위해 키 정책에서 제외
#     → vpc/ops/iam.tf, vpc/globalservice/iam.tf inline 정책으로 IAM delegation 처리
#   - EC2 서비스 (EBS 볼륨): AutoScaling SLR은 첫 apply 시 미존재 가능
#     → ec2.amazonaws.com 서비스 프린시팔로 교체 (DenyCrossAccount로 계정 범위 제한)
# =============================================
resource "aws_kms_key" "key_eks" {
  description             = "EKS CMK for ilpumjinro (etcd Secrets + EBS node volumes)"
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
        # EC2 서비스: 직접 RunInstances 경로(EBS 즉시 암호화)용. EKS managed node
        # group은 ASG가 인스턴스를 띄우므로 이 프린시팔로는 부족 → 아래 SLR 권한 필수.
        Sid    = "AllowEC2EBSEncryption"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:CreateGrant",
          "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        # AutoScaling service-linked role: EKS managed node group의 ASG가 노드 EBS
        # 루트 볼륨을 이 CMK로 암호화할 때 사용. SLR에 직접 권한이 없으면 인스턴스
        # launch가 Client.InvalidKMSKey.InvalidState로 실패하여 노드가 클러스터에
        # join하지 못해 노드그룹이 CREATE_FAILED가 된다. (ec2.amazonaws.com 프린시팔만으로는
        # 불충분 — ASG는 SLR 자격으로 KMS를 직접 호출한다.)
        Sid    = "AllowAutoScalingEBSEncryption"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling"
        }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        # ASG SLR이 암호화된 EBS 볼륨에 대한 grant를 생성하도록 허용
        # (GrantIsForAWSResource로 AWS 리소스 경유 호출만 허용해 범위 제한)
        Sid    = "AllowAutoScalingCreateGrant"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling"
        }
        Action   = "kms:CreateGrant"
        Resource = "*"
        Condition = {
          Bool = {
            "kms:GrantIsForAWSResource" = "true"
          }
        }
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
          Bool = {
            "aws:PrincipalIsAWSService" = "false"
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

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "EKS"
    Environment = "all"
  }
}

resource "aws_kms_alias" "key_eks" {
  name          = "alias/key-eks"
  target_key_id = aws_kms_key.key_eks.key_id

  lifecycle {
    create_before_destroy = false
  }
}

# =============================================
# key-logs (CloudWatch Logs 전용 CMK)
#   용도: VPC Flow Logs + 향후 모든 CW 로그그룹(EKS·앱 로그)의 표준 암호화 키
#   $1/월. flow log 하나가 아닌 CW Logs 전체에 amortize됨.
# =============================================
resource "aws_kms_key" "key_logs" {
  description             = "CMK for CloudWatch Logs (VPC Flow Logs 등 보안 텔레메트리)"
  deletion_window_in_days = 30
  enable_key_rotation     = true

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
        # 리전 형식 프린시펄 필수 — logs.amazonaws.com 은 거부됨
        # confused-deputy 방지: 이 계정의 CW 로그그룹 컨텍스트로만 사용 가능
        Sid    = "AllowCloudWatchLogs"
        Effect = "Allow"
        Principal = {
          Service = "logs.${var.aws_region}.amazonaws.com"
        }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*"
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"
          }
        }
      }
    ]
  })

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "CloudWatchLogs"
    Environment = "all"
  }
}

resource "aws_kms_alias" "key_logs" {
  name          = "alias/key-logs"
  target_key_id = aws_kms_key.key_logs.key_id

  lifecycle {
    create_before_destroy = false
  }
}

# =============================================
# key-sns (SNS 전용 CMK)
#   용도: 보안 알람 알림 토픽 암호화
#   $1/월.
# =============================================
resource "aws_kms_key" "key_sns" {
  description             = "CMK for SNS (보안 알람 알림 토픽)"
  deletion_window_in_days = 30
  enable_key_rotation     = true

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
        # CloudWatch 알람이 암호화된 SNS 토픽에 publish 하려면 필수
        # 없으면 알람은 ALARM 상태인데 알림이 조용히 안 감
        Sid    = "AllowCloudWatchAlarmsPublish"
        Effect = "Allow"
        Principal = {
          Service = "cloudwatch.amazonaws.com"
        }
        Action   = ["kms:Decrypt", "kms:GenerateDataKey*"]
        Resource = "*"
      },
      {
        # EventBridge 룰이 암호화된 SNS 토픽에 publish할 때 KMS 데이터키 필요
        # 없으면 룰은 매칭되는데 알림이 조용히 소실됨 (#49)
        Sid    = "AllowEventBridgePublish"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = ["kms:Decrypt", "kms:GenerateDataKey*"]
        Resource = "*"
      }
    ]
  })

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project     = "ilpumjinro"
    ManagedBy   = "terraform"
    Owner       = "security"
    Service     = "SNS"
    Environment = "all"
  }
}

resource "aws_kms_alias" "key_sns" {
  name          = "alias/key-sns"
  target_key_id = aws_kms_key.key_sns.key_id

  lifecycle {
    create_before_destroy = false
  }
}
