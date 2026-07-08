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

# Bedrock Knowledge Base 검색(RAG) — map_regulation이 규정 검색을 로컬 파일 대신
# KB로 승격할 때(USE_BEDROCK_KB=true) 사용. retrieval.py가 bedrock:Retrieve 호출.
# KB는 콘솔 Quick Create로 생성되므로 특정 KB ARN 대신 계정/리전 내 KB로 스코프.
resource "aws_iam_role_policy" "secops_orchestrator_bedrock_kb" {
  name = "bedrock-kb-retrieve"
  role = aws_iam_role.secops_orchestrator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "BedrockKnowledgeBaseRetrieve"
      Effect = "Allow"
      Action = [
        "bedrock:Retrieve",
      ]
      Resource = "arn:aws:bedrock:${var.aws_region}:${var.account_id}:knowledge-base/*"
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

# 트리거 SQS 소비 — secops-trigger.tf(GuardDuty 아닌 기존 무료 탐지 SNS → SQS)의
# 큐를 워커 poller가 폴링해 워크플로를 기동한다. 큐 ARN은 결정적(리전+계정+큐명)이라
# 루트 리소스를 크로스모듈 참조하지 않고 문자열로 구성한다.
resource "aws_iam_role_policy" "secops_orchestrator_trigger_sqs" {
  name = "secops-trigger-sqs-consume"
  role = aws_iam_role.secops_orchestrator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "SecOpsTriggerQueueConsume"
      Effect = "Allow"
      Action = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
      ]
      Resource = "arn:aws:sqs:${var.aws_region}:${var.account_id}:financial-secops-trigger"
    }]
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
