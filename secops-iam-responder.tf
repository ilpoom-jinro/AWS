# ──────────────────────────────────────────────────────────────────────────────
# 계정 탈취 IAM 회수 Lambda — VPC 밖(slack-broker.tf와 동일 패턴)
#
# 왜 VPC 밖인가: ops VPC(vpc2)는 IGW/NAT가 없는 격리망이고, IAM은 ap-northeast-2에
# PrivateLink 엔드포인트가 없다(us-east-1 전용 + Transit Gateway 필요 — 이 리전만 쓰는
# 지금 구조에 안 맞음). secops-orchestrator가 IAM을 직접 detach/deactivate 못 하므로,
# 이 Lambda가 대신 호출한다. Lambda 자체는 VpcConfig를 두지 않아(= VPC 미연결) AWS 관리형
# 네트워킹(인터넷 접근 가능)으로 IAM 글로벌 엔드포인트에 바로 닿는다.
#
# orchestrator ↔ 이 Lambda 경로: orchestrator는 vpc/ops/endpoints.tf의 Lambda Interface
# Endpoint + gitops/platform/cilium/allow-fqdn-secops-mas.yaml의 lambda FQDN 허용을 거쳐
# lambda:InvokeFunction으로 이 함수를 호출한다(vpc/ops/secops-role.tf 참고). dry-run
# 단계에서는 orchestrator가 이 Lambda를 아예 부르지 않는다(activities.py의
# revoke_iam_privilege 참고) — 실제 IAM 호출 경로 자체를 2차 승인 이후로 물리적으로 분리.
#
# 권한 이전: 기존 vpc/ops/secops-role.tf의 secops_orchestrator_iam_response 정책
# (Allow user/* detach/delete/update + Deny role/*·팀원 개인계정 보호)을 그대로 옮겼다 —
# least privilege: 강력한 회수 권한이 파드(공격 표면 넓음) 대신 이 호출 하나만 하는
# Lambda(공격 표면 좁음)에 있는 게 더 안전하다.
# ──────────────────────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# Lambda 패키징 — archive_file로 소스만 zip (slack-broker.tf와 동일, ECR 이미지 안 씀)
# ══════════════════════════════════════════════════════════════════════════════

data "archive_file" "secops_iam_responder" {
  type        = "zip"
  source_file = "${path.module}/lambda/secops-iam-responder/handler.py"
  output_path = "${path.module}/lambda/secops-iam-responder/build/iam-responder.zip"
}

# ══════════════════════════════════════════════════════════════════════════════
# IAM — Lambda 실행 역할
# ══════════════════════════════════════════════════════════════════════════════

resource "aws_iam_role" "secops_iam_responder_lambda" {
  name = "financial-secops-iam-responder-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    ManagedBy = "terraform"
    Component = "secops-iam-responder"
  }
}

# CloudWatch Logs 기본 실행 권한 (AWS 관리형 정책) — slack-broker Lambda와 동일
resource "aws_iam_role_policy_attachment" "secops_iam_responder_lambda_basic" {
  role       = aws_iam_role.secops_iam_responder_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# 계정 탈취 대응 — vpc/ops/secops-role.tf의 기존 secops_orchestrator_iam_response에서
# 그대로 이전한 정책. 강력한 권한(보안 대응 시스템 자체가 탈취되면 계정 전체를 무력화할
# 수 있는 권한)이라 이중으로 제한한다:
#   1) Allow는 user/*만 (role은 회수 대상 아님 — Allow에서 아예 제외)
#   2) Deny로 모든 role + 팀원 개인 계정을 명시적으로 보호(Allow보다 우선 적용)
# 실운영: 대응 대상이 늘어나면 이 Deny 목록을 계속 관리해야 함 — 향후 개인 계정에
# protected=true 같은 태그를 달고 태그 기반 Condition(aws:ResourceTag)으로 전환해
# 목록을 일일이 나열 안 해도 되게 바꾸는 걸 고려.
resource "aws_iam_role_policy" "secops_iam_responder_lambda_iam_response" {
  name = "secops-iam-account-takeover-response"
  role = aws_iam_role.secops_iam_responder_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IamAccountTakeoverResponse"
        Effect = "Allow"
        Action = [
          "iam:DetachUserPolicy",
          "iam:DetachRolePolicy",
          "iam:DeleteAccessKey",
          "iam:UpdateAccessKey",
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/*",
        ]
      },
      {
        Sid    = "IamAccountTakeoverResponseProtected"
        Effect = "Deny"
        Action = [
          "iam:DetachUserPolicy",
          "iam:DetachRolePolicy",
          "iam:DeleteAccessKey",
          "iam:UpdateAccessKey",
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*", # role은 전부 보호
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/security",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/infra",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/gh",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/sre",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/sj",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/minsu",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/onfrem",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/platform",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/migration",
        ]
      },
    ]
  })
}

# ══════════════════════════════════════════════════════════════════════════════
# Lambda 함수 — vpc_config 없음(= VPC 미연결). 위 헤더 설명 참고.
# ══════════════════════════════════════════════════════════════════════════════

resource "aws_lambda_function" "secops_iam_responder" {
  function_name = "financial-secops-iam-responder"
  description   = "계정 탈취 대응 — IAM 정책 detach / AccessKey 비활성화 (VPC 밖, secops-orchestrator가 invoke)"

  role             = aws_iam_role.secops_iam_responder_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 10
  memory_size      = 128
  filename         = data.archive_file.secops_iam_responder.output_path
  source_code_hash = data.archive_file.secops_iam_responder.output_base64sha256

  tags = {
    ManagedBy = "terraform"
    Component = "secops-iam-responder"
  }
}
