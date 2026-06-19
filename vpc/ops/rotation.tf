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
  }

  tags = {
    ManagedBy = "terraform"
  }
}

# SAR 배포 후 Lambda 실행 Role에 CMK 권한 추가
data "aws_lambda_function" "ops_rotation" {
  function_name = "financial-ops-rds-rotation"

  depends_on = [aws_serverlessapplicationrepository_cloudformation_stack.ops_rds_rotation]
}

resource "aws_iam_role_policy" "rotation_lambda_kms" {
  name = "kms-for-secretsmanager"
  role = reverse(split("/", data.aws_lambda_function.ops_rotation.role))[0]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowCMKForSecretsManager"
      Effect = "Allow"
      Action = [
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:DescribeKey",
      ]
      Resource = var.kms_key_secretsmanager_arn
    }]
  })
}
