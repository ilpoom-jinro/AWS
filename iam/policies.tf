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
        "s3:PutBucketPolicy",          # S3 버킷 정책 설정
        "s3:PutBucketLogging",         # S3 액세스 로그 설정
        "ec2:CreateFlowLogs",          # VPC Flow Logs 구성
        "cloudwatch:PutMetricAlarm",   # 금융 알람 구성
        "guardduty:CreateDetector",    # GuardDuty 활성화
        "securityhub:EnableSecurityHub", # Security Hub 활성화
        "iam:AttachGroupPolicy",       # IAM 권한 설정
        "iam:CreatePolicy",            # IAM 정책 생성
        "iam:UpdateAccountPasswordPolicy" # 비밀번호 정책 설정
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
# prod에서 삭제는 아래 deny 정책으로 별도 차단
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
# Condition으로 Environment=prod 태그 리소스에만 적용
# =============================================
resource "aws_iam_policy" "deny_prod_destructive" {
  name = "deny-prod-destructive-actions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
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
      Condition = {
        StringEquals = {
          # prod 태그 붙은 리소스에만 이 차단 적용
          "aws:ResourceTag/Environment" = "prod"
        }
      }
    }]
  })
}

# platform, sre 그룹에 prod 차단 정책 적용
resource "aws_iam_group_policy_attachment" "platform_deny_prod" {
  group      = aws_iam_group.platform_engineers.name
  policy_arn = aws_iam_policy.deny_prod_destructive.arn
}

resource "aws_iam_group_policy_attachment" "sre_deny_prod" {
  group      = aws_iam_group.sre_engineers.name
  policy_arn = aws_iam_policy.deny_prod_destructive.arn
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

# onfrem 액세스 키 (collector 인증용)
resource "aws_iam_access_key" "onfrem" {
  user = aws_iam_user.onfrem.name
}