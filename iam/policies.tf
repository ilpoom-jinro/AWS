# =============================================
# AWS 관리형 정책 연결
# policy_arn = AWS가 미리 만들어놓은 정책의 고유 주소
# =============================================

# infra-admin → 전체 권한
resource "aws_iam_group_policy_attachment" "infra_admin" {
  group      = aws_iam_group.infra_admin.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# security-engineers → 보안 서비스 읽기 권한
resource "aws_iam_group_policy_attachment" "security_audit" {
  group      = aws_iam_group.security_engineers.name
  policy_arn = "arn:aws:iam::aws:policy/SecurityAudit"
}

# =============================================
# security 추가 권한 (직접 만든 정책)
# SecurityAudit은 읽기만 가능해서 필요한 설정 변경 권한을 따로 추가
# =============================================
resource "aws_iam_policy" "security_extra" {
  name = "security-extra-permissions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutBucketPolicy",              # S3 버킷 정책 설정
        "s3:PutBucketLogging",             # S3 액세스 로그 설정
        "ec2:CreateFlowLogs",              # VPC Flow Logs 구성
        "cloudwatch:PutMetricAlarm",       # 금융 알람 구성
        "guardduty:CreateDetector",        # GuardDuty 활성화
        "securityhub:EnableSecurityHub",   # Security Hub 활성화
        "securityhub:GetFindings",         # 보안 발견 사항 조회
        "securityhub:DescribeHub",         # Security Hub 설정 조회
        "securityhub:ListFindings",        # 보안 발견 사항 목록
        "securityhub:GetInsights",         # 인사이트 조회
        "iam:AttachGroupPolicy",           # IAM 권한 설정
        "iam:CreatePolicy",                # IAM 정책 생성
        "iam:UpdateAccountPasswordPolicy", # 비밀번호 정책 설정
        "iam:UpdateAccountPasswordPolicy", # 비밀번호 정책 설정
        # KMS 긴급 대응 권한 (financial-kms-admin-role Assume 불가 시)
        "kms:CreateKey",           # CMK 생성
        "kms:PutKeyPolicy",        # 키 정책 설정
        "kms:ScheduleKeyDeletion", # 키 삭제 예약
        "kms:CancelKeyDeletion",   # 키 삭제 취소
        "kms:DisableKey",          # 키 비활성화
        "kms:EnableKeyRotation"    # 키 로테이션 활성화
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_group_policy_attachment" "security_extra" {
  group      = aws_iam_group.security_engineers.name
  policy_arn = aws_iam_policy.security_extra.arn
}

# platform-engineers → IAM 제외 전체 권한
resource "aws_iam_group_policy_attachment" "platform_power_user" {
  group      = aws_iam_group.platform_engineers.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

# sre-engineers → IAM 제외 전체 권한
resource "aws_iam_group_policy_attachment" "sre_power_user" {
  group      = aws_iam_group.sre_engineers.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

# =============================================
# 위험 행동 차단 정책 (platform, sre 공통)
# 금융권 보안 요건 - 태그/환경 구분 없이 무조건 차단
# infra-admin만 AdministratorAccess로 해당 작업 수행 가능
# =============================================
resource "aws_iam_policy" "deny_destructive" {
  name = "deny-destructive-actions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "DenyDestructiveActions"
      Effect = "Deny"
      Action = [
        "ec2:TerminateInstances", # 서버 종료
        "rds:DeleteDBInstance",   # DB 삭제
        "eks:DeleteCluster",      # EKS 클러스터 삭제
        "s3:DeleteBucket",        # S3 버킷 삭제
        "iam:DeleteUser",         # 사용자 삭제
        "iam:DeleteRole"          # 역할 삭제
      ]
      Resource = "*"
      # Condition 없음 = 환경 태그와 무관하게 항상 Deny
    }]
  })
}

# platform, sre 그룹에 차단 정책 적용
resource "aws_iam_group_policy_attachment" "platform_deny_destructive" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.platform_engineers.name
  policy_arn = aws_iam_policy.deny_destructive.arn
}

resource "aws_iam_group_policy_attachment" "sre_deny_destructive" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.sre_engineers.name
  policy_arn = aws_iam_policy.deny_destructive.arn
}

# =============================================
# onfrem: 온프레미스 collector용 인라인 정책
# CloudWatch Logs (보안 감사 로그) + AMP (Prometheus 매트릭) 전송 권한
# =============================================
resource "aws_iam_user_policy" "onfrem_collector" {
  name = "onfrem-collector-policy"
  user = aws_iam_user.onfrem.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogsWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Sid      = "PrometheusRemoteWrite"
        Effect   = "Allow"
        Action   = ["aps:RemoteWrite"]
        Resource = "*"
      }
    ]
  })
}

# =============================================
# [DEV ONLY] 개발 기간 임시 AdministratorAccess
# dev_mode = true 일 때만 활성화
# 개발 완료 후 이 블록 전체 삭제 예정
# =============================================
resource "aws_iam_group_policy_attachment" "security_admin_dev" {
  count      = var.dev_mode ? 1 : 0
  group      = aws_iam_group.security_engineers.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_group_policy_attachment" "platform_admin_dev" {
  count      = var.dev_mode ? 1 : 0
  group      = aws_iam_group.platform_engineers.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_group_policy_attachment" "sre_admin_dev" {
  count      = var.dev_mode ? 1 : 0
  group      = aws_iam_group.sre_engineers.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# =============================================
# Access Key 신규 생성 차단 정책 (#42)
# dev_mode = true  → 정책 미적용 (개발 중 키 발급 필요할 수 있으므로)
# dev_mode = false → 전 그룹 Access Key 생성 차단
# 키 생성은 Terraform(GitHub Actions Role)을 통해서만 가능
# 기존에 있는 키는 삭제되지 않고 그대로 작동함
# =============================================
resource "aws_iam_policy" "deny_create_access_key" {
  name = "deny-create-access-key"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "DenyCreateAccessKey"
      Effect   = "Deny"
      Action   = ["iam:CreateAccessKey"]
      Resource = "*"
    }]
  })
}

# infra-admin 그룹에 적용
resource "aws_iam_group_policy_attachment" "infra_deny_access_key" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.infra_admin.name
  policy_arn = aws_iam_policy.deny_create_access_key.arn
}

# security-engineers 그룹에 적용
resource "aws_iam_group_policy_attachment" "security_deny_access_key" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.security_engineers.name
  policy_arn = aws_iam_policy.deny_create_access_key.arn
}

# platform-engineers 그룹에 적용
resource "aws_iam_group_policy_attachment" "platform_deny_access_key" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.platform_engineers.name
  policy_arn = aws_iam_policy.deny_create_access_key.arn
}

# sre-engineers 그룹에 적용
resource "aws_iam_group_policy_attachment" "sre_deny_access_key" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.sre_engineers.name
  policy_arn = aws_iam_policy.deny_create_access_key.arn
}

# onfrem-engineers 그룹에 적용
resource "aws_iam_group_policy_attachment" "onfrem_deny_access_key" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.onfrem_engineers.name
  policy_arn = aws_iam_policy.deny_create_access_key.arn
}

# =============================================
# CloudShell 접근 통제
# infra-admin 외 전 그룹 CloudShell 사용 차단
# dev_mode = true  → 미적용 (개발 중 필요할 수 있으므로)
# dev_mode = false → security, platform, sre, onfrem 차단
# =============================================
resource "aws_iam_policy" "deny_cloudshell" {
  name = "deny-cloudshell"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "DenyCloudShell"
      Effect   = "Deny"
      Action   = ["cloudshell:*"]
      Resource = "*"
    }]
  })
}

# security-engineers 차단
resource "aws_iam_group_policy_attachment" "security_deny_cloudshell" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.security_engineers.name
  policy_arn = aws_iam_policy.deny_cloudshell.arn
}

# platform-engineers 차단
resource "aws_iam_group_policy_attachment" "platform_deny_cloudshell" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.platform_engineers.name
  policy_arn = aws_iam_policy.deny_cloudshell.arn
}

# sre-engineers 차단
resource "aws_iam_group_policy_attachment" "sre_deny_cloudshell" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.sre_engineers.name
  policy_arn = aws_iam_policy.deny_cloudshell.arn
}

# =============================================
# MAS 팀 전용 권한 정책
# Bedrock, ECR, EKS 조회, CloudWatch/Logs 읽기,
# Prometheus 쿼리, 보안 서비스 읽기, S3 KB, SecretsManager, RDS IAM 인증
# =============================================
resource "aws_iam_policy" "mas_policy" {
  name = "mas-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockAll"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:ListFoundationModels",
          "bedrock:GetFoundationModel",
          "bedrock:RetrieveAndGenerate",
          "bedrock:Retrieve",
          "bedrock:ListKnowledgeBases",
          "bedrock:GetKnowledgeBase"
        ]
        Resource = "*"
      },
      {
        Sid    = "ECRPushPull"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeRepositories",
          "ecr:DescribeImages",
          "ecr:ListImages"
        ]
        Resource = "*"
      },
      {
        Sid    = "EKSDescribe"
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster",
          "eks:ListClusters",
          "eks:ListNodegroups",
          "eks:DescribeNodegroup"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchAndLogsRead"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
          "cloudwatch:DescribeAlarms",
          "logs:FilterLogEvents",
          "logs:GetLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:StartQuery",
          "logs:GetQueryResults",
          "logs:StopQuery"
        ]
        Resource = "*"
      },
      {
        Sid    = "PrometheusQuery"
        Effect = "Allow"
        Action = [
          "aps:QueryMetrics",
          "aps:GetMetricMetadata",
          "aps:ListWorkspaces",
          "aps:DescribeWorkspace",
          "aps:GetLabels",
          "aps:GetSeries"
        ]
        Resource = "*"
      },
      {
        Sid    = "SecurityServicesRead"
        Effect = "Allow"
        Action = [
          "cloudtrail:LookupEvents",
          "cloudtrail:GetTrailStatus",
          "cloudtrail:DescribeTrails",
          "guardduty:GetFindings",
          "guardduty:ListFindings",
          "guardduty:GetDetector",
          "guardduty:ListDetectors",
          "securityhub:GetFindings",
          "securityhub:ListFindings",
          "securityhub:GetInsights"
        ]
        Resource = "*"
      },
      {
        Sid    = "S3KnowledgeBaseRead"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "arn:aws:s3:::ilpumjinro-kb-*",
          "arn:aws:s3:::ilpumjinro-kb-*/*"
        ]
      },
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
          "secretsmanager:ListSecrets"
        ]
        Resource = "arn:aws:secretsmanager:*:*:secret:financial-*"
      },
      {
        Sid      = "RDSIAMAuth"
        Effect   = "Allow"
        Action   = ["rds-db:connect"]
        Resource = "arn:aws:rds-db:*:*:dbuser:*/mas_sdk_user"
      }
    ]
  })
}

# mas 그룹 → mas-policy 항상 연결
resource "aws_iam_group_policy_attachment" "mas_policy" {
  group      = aws_iam_group.mas.name
  policy_arn = aws_iam_policy.mas_policy.arn
}

# mas 그룹 → Access Key 신규 생성 차단 (prod 환경)
resource "aws_iam_group_policy_attachment" "mas_deny_access_key" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.mas.name
  policy_arn = aws_iam_policy.deny_create_access_key.arn
}

# mas 그룹 → CloudShell 차단 (prod 환경)
resource "aws_iam_group_policy_attachment" "mas_deny_cloudshell" {
  count      = var.dev_mode ? 0 : 1
  group      = aws_iam_group.mas.name
  policy_arn = aws_iam_policy.deny_cloudshell.arn
}

# [DEV ONLY] mas 그룹 → 개발 기간 임시 AdministratorAccess
resource "aws_iam_group_policy_attachment" "mas_admin_dev" {
  count      = var.dev_mode ? 1 : 0
  group      = aws_iam_group.mas.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
