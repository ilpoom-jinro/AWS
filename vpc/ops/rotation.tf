# ──────────────────────────────────────────────────────────────────────────────
# Secrets Manager 로테이션 Lambda — ops RDS PostgreSQL
# SecretsManagerRDSPostgreSQLRotationSingleUser SAR 앱으로 배포
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_security_group" "rotation_lambda" {
  name        = "financial-vpc2-rotation-lambda-sg"
  description = "Secrets Manager rotation Lambda for ops RDS"
  vpc_id      = aws_vpc.this.id

  egress {
    description     = "Allow PostgreSQL to ops RDS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.rds.id]
  }

  egress {
    description = "Allow HTTPS to VPC Endpoints (Secrets Manager, KMS)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name      = "financial-vpc2-rotation-lambda-sg"
    ManagedBy = "terraform"
  }
}

resource "aws_security_group_rule" "rds_from_rotation_lambda" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds.id
  source_security_group_id = aws_security_group.rotation_lambda.id
  description              = "Allow PostgreSQL from Secrets Manager rotation Lambda"
}

data "aws_serverlessapplicationrepository_application" "postgres_rotation" {
  # SAR 앱은 us-east-1 게시본. 서울 SAR authorizer 장애 회피 위해 us-east-1로 조회.
  provider         = aws.us_east_1
  application_id   = "arn:aws:serverlessrepo:us-east-1:297356227824:applications/SecretsManagerRDSPostgreSQLRotationSingleUser"
  semantic_version = "1.1.367"
}

resource "aws_serverlessapplicationrepository_cloudformation_stack" "ops_rds_rotation" {
  name             = "financial-ops-rds-rotation"
  application_id   = data.aws_serverlessapplicationrepository_application.postgres_rotation.application_id
  semantic_version = data.aws_serverlessapplicationrepository_application.postgres_rotation.semantic_version
  capabilities     = data.aws_serverlessapplicationrepository_application.postgres_rotation.required_capabilities

  parameters = {
    endpoint            = "https://secretsmanager.${var.aws_region}.amazonaws.com"
    functionName        = "financial-ops-rds-rotation"
    vpcSubnetIds        = join(",", [aws_subnet.private_a.id, aws_subnet.private_b.id])
    vpcSecurityGroupIds = aws_security_group.rotation_lambda.id
    excludeCharacters   = "/@\"':"
    # SAR 템플릿이 Lambda execution role 생성 시점에 KMS 권한을 내장.
    # 기존엔 rotation_lambda_kms policy로 사후 부착했는데, destroy/apply마다
    # role 이름이 바뀌어 재생성·권한 갭 → createSecret KMS Decrypt 실패 → 토큰 충돌.
    kmsKeyArn = var.kms_key_secretsmanager_arn
  }

  tags = {
    ManagedBy = "terraform"
  }
}

data "aws_lambda_function" "ops_rotation" {
  # destroy 시 rotation_lambda_arn_override가 주어지면 이 조회를 건너뛴다.
  # Lambda가 이미 사라진 상태에서는 조회 자체가 404로 실패해 plan이 막히기 때문.
  count         = var.rotation_lambda_arn_override == null ? 1 : 0
  function_name = "financial-ops-rds-rotation"

  depends_on = [aws_serverlessapplicationrepository_cloudformation_stack.ops_rds_rotation]
}
