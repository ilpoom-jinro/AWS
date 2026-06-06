# ──────────────────────────────────────────────────────────────────────────────
# VPC 2 — RDS PostgreSQL 16 (Ops DB)
# 용도: Bedrock AI Agent 주식 분석 보고서, 내부 운영 데이터, ArgoCD 메타데이터
# ──────────────────────────────────────────────────────────────────────────────

# ── DB Subnet Group ───────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "ops" {
  name        = "financial-vpc2-db-subnet-group"
  description = "DB subnet group for financial-ops RDS"
  subnet_ids  = [aws_subnet.db_a.id, aws_subnet.db_b.id]

  tags = {
    Name = "financial-vpc2-db-subnet-group"
  }
}

# ── Parameter Group ───────────────────────────────────────────────────────────

resource "aws_db_parameter_group" "ops" {
  name        = "financial-vpc2-pg16"
  family      = "postgres16"
  description = "PostgreSQL 16 parameter group for financial-ops"

  tags = {
    Name = "financial-vpc2-pg16"
  }
}

# ── RDS Instance ──────────────────────────────────────────────────────────────


resource "aws_db_instance" "ops" {
  identifier = "financial-ops-db"

  engine         = "postgres"
  engine_version = "16"

  instance_class = var.rds_instance_class
  multi_az       = var.rds_multi_az

  db_name  = "financial_ops"
  username = "financial_admin"
  password = var.rds_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.ops.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.ops.name

  allocated_storage = 100
  storage_type      = "gp3"
  storage_encrypted = true

  backup_retention_period = 0
  backup_window           = "18:00-19:00"
  maintenance_window      = "sun:19:00-sun:20:00"

  auto_minor_version_upgrade = false
  deletion_protection        = true
  skip_final_snapshot        = false
  final_snapshot_identifier  = "financial-ops-db-final-snapshot"

  performance_insights_enabled = true

  tags = {
    Name = "financial-ops-db"
  }
}

# ── Bedrock Agent Lambda SG 접근 (추후 추가 예정) ─────────────────────────────
# ingress rule은 aws_security_group_rule로 분리하여 ops/rds.tf에 추가 예정:
#
# resource "aws_security_group_rule" "rds_from_bedrock_lambda" {
#   type                     = "ingress"
#   from_port                = 5432
#   to_port                  = 5432
#   protocol                 = "tcp"
#   security_group_id        = aws_security_group.rds.id
#   source_security_group_id = <bedrock_lambda_sg_id>
#   description              = "Allow PostgreSQL from Bedrock Agent Lambda"
# }
