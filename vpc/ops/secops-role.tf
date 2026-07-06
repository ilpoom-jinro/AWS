# 이 파일은 SecOps 전용 역할 + 텔레메트리 정책을 정의함.
# 적용 시: pod-identity.tf 의 aws_eks_pod_identity_association.mas_orchestrator_secops 를
#   삭제(또는 role_arn 을 이 역할로 변경)하고, 아래 association 을 사용한다. (중복 association 금지)

resource "aws_iam_role" "secops_orchestrator" {
  name        = "financial-ops-secops-orchestrator-role"
  description = "SecOps Orchestrator - Bedrock + security telemetry (Flow Logs / CloudTrail / GuardDuty)"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowEKSPodIdentity"
      Effect = "Allow"
      Principal = {
        Service = "pods.eks.amazonaws.com"
      }
      Action = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })

  tags = {
    ManagedBy = "terraform"
    Scenario  = "secops"
  }
}

# Bedrock (규제 위반 분석 — Nova/Haiku Converse) — FinOps 역할과 동일 범위
resource "aws_iam_role_policy" "secops_orchestrator_bedrock_runtime" {
  name = "bedrock-runtime-access"
  role = aws_iam_role.secops_orchestrator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "BedrockRuntimeAccess"
      Effect = "Allow"
      Action = [
        "bedrock:Converse",
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:GetFoundationModel",
        "bedrock:GetInferenceProfile",
      ]
      Resource = "*"
    }]
  })
}

# 보안 텔레메트리 조회 — SecOps 탐지/증적의 실데이터 소스
resource "aws_iam_role_policy" "secops_orchestrator_telemetry" {
  name = "secops-telemetry-read"
  role = aws_iam_role.secops_orchestrator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "VPCFlowLogsRead"
        Effect = "Allow"
        Action = [
          "ec2:DescribeFlowLogs",
          "ec2:DescribeNetworkInterfaces",
          # Flow Logs 대상이 CloudWatch Logs인 경우의 조회 권한
          "logs:FilterLogEvents",
          "logs:GetLogEvents",
          "logs:StartQuery",
          "logs:GetQueryResults",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudTrailLookup"
        Effect = "Allow"
        Action = [
          "cloudtrail:LookupEvents",
          "cloudtrail:GetTrailStatus",
          "cloudtrail:DescribeTrails",
        ]
        Resource = "*"
      },
      {
        Sid    = "GuardDutyRead"
        Effect = "Allow"
        Action = [
          "guardduty:ListDetectors",
          "guardduty:ListFindings",
          "guardduty:GetFindings",
        ]
        Resource = "*"
      },
    ]
  })
}

# 감사 로그 DB 등 공통 접근이 필요하면 mas-policy 도 부착 (FinOps 역할과 동일)
resource "aws_iam_role_policy_attachment" "secops_orchestrator_mas" {
  role       = aws_iam_role.secops_orchestrator.name
  policy_arn = "arn:aws:iam::${var.account_id}:policy/mas-policy"
}

# SecOps 파드가 이 전용 역할을 쓰도록 association.
# ※ 기존 pod-identity.tf 의 "mas_orchestrator_secops" association 은 제거해야 함
#    (한 service_account 에 두 association 이 있으면 충돌).
resource "aws_eks_pod_identity_association" "secops_orchestrator" {
  cluster_name    = aws_eks_cluster.ops.name
  namespace       = "secops-mas"
  service_account = "secops-orchestrator"
  role_arn        = aws_iam_role.secops_orchestrator.arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}
