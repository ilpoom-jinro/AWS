# ──────────────────────────────────────────────────────────────────────────────
# Slack HITL 공용 브로커 — 전송 계층 (API Gateway + Lambda 2개 + SQS 2개)
#
# 범위: Slack ↔ AWS 사이의 "전송"만 담당한다.
#   - inbound : Slack Interactivity 콜백(버튼 클릭) → 서명 검증 → SQS
#   - outbound: SQS 메시지 → Slack chat.postMessage
#
# 이번 작업에서 하지 않는 것 (다음 단계로 미룸):
#   - bot.py 수정 (Socket Mode 제거, SQS 연동) — 안 건드림
#   - Cilium 정책 수정 — 안 건드림
#   - SNS 토픽 / secops-trigger.tf 수정 — 안 건드림
#   - signing_secret 값 자체의 Secrets Manager 주입 / ExternalSecret 매핑 — 다음 단계
#   - inbound 큐를 실제로 폴링해 Temporal에 넘기는 in-cluster 컴포넌트 — 다음 단계
#
# 격리 제약: 아래 Lambda 2개는 vpc_config를 두지 않는다(= VPC 미연결).
#   ops VPC(vpc2)는 IGW/NAT가 없는 격리망이므로, Lambda를 그 VPC에 붙이면
#   slack.com·Secrets Manager 퍼블릭 엔드포인트에 닿기 위해 NAT가 필요해진다.
#   VPC 밖에 두면 Lambda 기본 네트워킹(AWS 관리형, 인터넷 접근 가능)을 그대로 쓸 수
#   있어 NAT 자체가 필요 없다 — ops VPC의 "IGW/NAT 0" 원칙은 그대로 유지된다.
#
# 재사용 패턴: SQS 큐 구성(SSE-SQS 관리형 암호화, redrive_policy, DLQ retention)은
#   secops-trigger.tf의 financial-secops-trigger 큐와 동일한 패턴을 따른다.
# ──────────────────────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# SQS — outbound (Slack로 나가는 방향: MAS/봇 → 이 큐 → outbound Lambda → Slack)
# ══════════════════════════════════════════════════════════════════════════════

# 처리 실패 메시지 보관 (원인 분석용) — secops-trigger.tf의 DLQ 패턴과 동일
resource "aws_sqs_queue" "slack_hitl_outbound_dlq" {
  name                      = "financial-slack-hitl-outbound-dlq"
  message_retention_seconds = 1209600 # 14일

  # SSE-SQS(관리형 SSE) — 별도 KMS 키 정책 불필요. 미설정 시 trivy AVD-AWS-0096(HIGH).
  sqs_managed_sse_enabled = true

  tags = {
    Name      = "financial-slack-hitl-outbound-dlq"
    ManagedBy = "terraform"
    Component = "slack-hitl-broker"
  }
}

# outbound Lambda(event source mapping)가 폴링하는 큐.
# visibility_timeout은 outbound Lambda timeout(10초)의 6배 이상으로 설정
# (AWS 권장값 — Lambda가 처리 중인 메시지가 다른 워커에 재노출되는 것을 방지).
resource "aws_sqs_queue" "slack_hitl_outbound" {
  name                       = "financial-slack-hitl-outbound"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 345600 # 4일

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.slack_hitl_outbound_dlq.arn
    maxReceiveCount     = 5
  })

  sqs_managed_sse_enabled = true

  tags = {
    Name      = "financial-slack-hitl-outbound"
    ManagedBy = "terraform"
    Component = "slack-hitl-broker"
  }
}

# ══════════════════════════════════════════════════════════════════════════════
# SQS — inbound (Slack에서 들어오는 방향: Slack → inbound Lambda → 이 큐 → 향후 in-cluster poller)
# ══════════════════════════════════════════════════════════════════════════════

resource "aws_sqs_queue" "slack_hitl_inbound_dlq" {
  name                      = "financial-slack-hitl-inbound-dlq"
  message_retention_seconds = 1209600 # 14일

  sqs_managed_sse_enabled = true

  tags = {
    Name      = "financial-slack-hitl-inbound-dlq"
    ManagedBy = "terraform"
    Component = "slack-hitl-broker"
  }
}

# 소비자는 아직 없음(다음 단계에서 in-cluster poller가 폴링 예정) — secops-trigger의
# financial-secops-trigger 큐와 동일하게 visibility_timeout=300초로 맞춰둔다
# (poller가 워크플로 기동에 걸리는 시간 여유).
resource "aws_sqs_queue" "slack_hitl_inbound" {
  name                       = "financial-slack-hitl-inbound"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 345600 # 4일

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.slack_hitl_inbound_dlq.arn
    maxReceiveCount     = 5
  })

  sqs_managed_sse_enabled = true

  tags = {
    Name      = "financial-slack-hitl-inbound"
    ManagedBy = "terraform"
    Component = "slack-hitl-broker"
  }
}

# ══════════════════════════════════════════════════════════════════════════════
# Lambda 패키징 — archive_file로 소스만 zip. ECR/컨테이너 이미지 빌드 안 씀.
# ══════════════════════════════════════════════════════════════════════════════

data "archive_file" "slack_inbound" {
  type        = "zip"
  source_file = "${path.module}/lambda/slack-broker/inbound/handler.py"
  output_path = "${path.module}/lambda/slack-broker/inbound/build/inbound.zip"
}

data "archive_file" "slack_outbound" {
  type        = "zip"
  source_file = "${path.module}/lambda/slack-broker/outbound/handler.py"
  output_path = "${path.module}/lambda/slack-broker/outbound/build/outbound.zip"
}

# ══════════════════════════════════════════════════════════════════════════════
# IAM — Lambda 실행 역할 (레포에 lambda.amazonaws.com assume role 전례 0, 신규 작성)
# ══════════════════════════════════════════════════════════════════════════════

# ── inbound Lambda 역할 ───────────────────────────────────────────────────────
resource "aws_iam_role" "slack_inbound_lambda" {
  name = "financial-slack-inbound-lambda-role"

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
    Component = "slack-hitl-broker"
  }
}

# CloudWatch Logs 기본 실행 권한 (AWS 관리형 정책)
resource "aws_iam_role_policy_attachment" "slack_inbound_lambda_basic" {
  role       = aws_iam_role.slack_inbound_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# signing_secret 조회(Secrets Manager + KMS 복호화) + inbound 큐 SendMessage만 허용
resource "aws_iam_role_policy" "slack_inbound_lambda" {
  name = "slack-inbound-secrets-and-sqs"
  role = aws_iam_role.slack_inbound_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadSlackHitlSecret"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.slack_hitl_tokens.arn
      },
      {
        Sid      = "DecryptSlackHitlSecret"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = data.aws_kms_key.key_secretsmanager.arn
      },
      {
        Sid      = "SendToInboundQueue"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.slack_hitl_inbound.arn
      }
    ]
  })
}

# ── outbound Lambda 역할 ──────────────────────────────────────────────────────
resource "aws_iam_role" "slack_outbound_lambda" {
  name = "financial-slack-outbound-lambda-role"

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
    Component = "slack-hitl-broker"
  }
}

resource "aws_iam_role_policy_attachment" "slack_outbound_lambda_basic" {
  role       = aws_iam_role.slack_outbound_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# bot token 조회(Secrets Manager + KMS 복호화) + outbound 큐 소비(event source mapping이
# 이 역할로 SQS를 폴링하므로 ReceiveMessage/DeleteMessage/GetQueueAttributes 필요)
resource "aws_iam_role_policy" "slack_outbound_lambda" {
  name = "slack-outbound-secrets-and-sqs"
  role = aws_iam_role.slack_outbound_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadSlackHitlSecret"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.slack_hitl_tokens.arn
      },
      {
        Sid      = "DecryptSlackHitlSecret"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = data.aws_kms_key.key_secretsmanager.arn
      },
      {
        Sid    = "ConsumeOutboundQueue"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
        ]
        Resource = aws_sqs_queue.slack_hitl_outbound.arn
      }
    ]
  })
}

# ══════════════════════════════════════════════════════════════════════════════
# Lambda 함수 2개 — vpc_config 없음(= VPC 미연결). 위 격리 제약 설명 참고.
# ══════════════════════════════════════════════════════════════════════════════

resource "aws_lambda_function" "slack_inbound" {
  function_name = "financial-slack-inbound"
  description   = "Slack Interactivity 콜백 서명 검증 후 inbound SQS로 전달"

  role             = aws_iam_role.slack_inbound_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 10
  memory_size      = 128
  filename         = data.archive_file.slack_inbound.output_path
  source_code_hash = data.archive_file.slack_inbound.output_base64sha256

  environment {
    variables = {
      SLACK_HITL_SECRET_ARN = aws_secretsmanager_secret.slack_hitl_tokens.arn
      INBOUND_QUEUE_URL     = aws_sqs_queue.slack_hitl_inbound.id
    }
  }

  tags = {
    ManagedBy = "terraform"
    Component = "slack-hitl-broker"
  }
}

resource "aws_lambda_function" "slack_outbound" {
  function_name = "financial-slack-outbound"
  description   = "outbound SQS 메시지를 소비해 Slack chat.postMessage 호출"

  role             = aws_iam_role.slack_outbound_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 10
  memory_size      = 128
  filename         = data.archive_file.slack_outbound.output_path
  source_code_hash = data.archive_file.slack_outbound.output_base64sha256

  environment {
    variables = {
      SLACK_HITL_SECRET_ARN = aws_secretsmanager_secret.slack_hitl_tokens.arn
    }
  }

  tags = {
    ManagedBy = "terraform"
    Component = "slack-hitl-broker"
  }
}

# outbound 큐를 outbound Lambda의 트리거로 연결 (Lambda 서비스가 slack_outbound_lambda
# 역할로 SQS를 폴링). batch_size=1: 메시지 하나당 Slack API 호출 하나로 단순화.
resource "aws_lambda_event_source_mapping" "slack_outbound" {
  event_source_arn = aws_sqs_queue.slack_hitl_outbound.arn
  function_name    = aws_lambda_function.slack_outbound.arn
  batch_size       = 1
}

# ══════════════════════════════════════════════════════════════════════════════
# API Gateway REST API (v1) — HTTP API(apigatewayv2) 아님. WAFv2는 REST API에만 붙는다.
# ══════════════════════════════════════════════════════════════════════════════

resource "aws_api_gateway_rest_api" "slack_broker" {
  name        = "financial-slack-broker"
  description = "Slack HITL 공용 브로커 — Interactivity 콜백 수신용 REST API"

  # REGIONAL 필수: waf.tf의 service_alb Web ACL이 scope=REGIONAL이라, 기본값인
  # EDGE(CloudFront 경유)로 두면 아래 aws_wafv2_web_acl_association이 실패한다.
  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# 슬랙 콜백용 POST 라우트 1개: POST /callback
resource "aws_api_gateway_resource" "slack_callback" {
  rest_api_id = aws_api_gateway_rest_api.slack_broker.id
  parent_id   = aws_api_gateway_rest_api.slack_broker.root_resource_id
  path_part   = "callback"
}

# Slack이 외부에서 직접 호출하므로 AWS SigV4 인증 없음(NONE) — 서명 검증은
# inbound Lambda 내부에서 X-Slack-Signature로 수행한다.
resource "aws_api_gateway_method" "slack_callback_post" {
  rest_api_id   = aws_api_gateway_rest_api.slack_broker.id
  resource_id   = aws_api_gateway_resource.slack_callback.id
  http_method   = "POST"
  authorization = "NONE"
}

# Lambda 프록시 통합 — 요청 원본(헤더/바디)을 그대로 inbound Lambda에 전달
resource "aws_api_gateway_integration" "slack_callback_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.slack_broker.id
  resource_id             = aws_api_gateway_resource.slack_callback.id
  http_method             = aws_api_gateway_method.slack_callback_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.slack_inbound.invoke_arn
}

# API Gateway가 inbound Lambda를 호출할 수 있도록 허용
resource "aws_lambda_permission" "apigw_invoke_slack_inbound" {
  statement_id  = "AllowAPIGatewayInvokeSlackInbound"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.slack_inbound.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.slack_broker.execution_arn}/*/POST/callback"
}

# method/integration 변경 시 재배포되도록 triggers로 해시값을 물림
resource "aws_api_gateway_deployment" "slack_broker" {
  rest_api_id = aws_api_gateway_rest_api.slack_broker.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.slack_callback.id,
      aws_api_gateway_method.slack_callback_post.id,
      aws_api_gateway_integration.slack_callback_lambda.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [aws_api_gateway_integration.slack_callback_lambda]
}

resource "aws_api_gateway_stage" "slack_broker" {
  rest_api_id   = aws_api_gateway_rest_api.slack_broker.id
  deployment_id = aws_api_gateway_deployment.slack_broker.id
  stage_name    = "prod"

  tags = {
    ManagedBy = "terraform"
    Component = "slack-hitl-broker"
  }
}

# ══════════════════════════════════════════════════════════════════════════════
# WAF 연결 — 기존 REGIONAL Web ACL(waf.tf:14, #74)을 API Gateway 스테이지에도 연결.
# 단일 Web ACL을 ALB(ingress 어노테이션 방식)와 API GW(association 리소스)에
# 동시에 연결하는 것 — WAFv2 REGIONAL Web ACL은 여러 리소스에 연결 가능하고
# 기본요금이 추가되지 않는다.
# ══════════════════════════════════════════════════════════════════════════════

resource "aws_wafv2_web_acl_association" "slack_broker_api" {
  resource_arn = aws_api_gateway_stage.slack_broker.arn
  web_acl_arn  = aws_wafv2_web_acl.service_alb.arn
}
