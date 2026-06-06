# ──────────────────────────────────────────────────────────────────────────────
# VPC 1 — RDS PostgreSQL 16 (Service DB)
# 용도: demo-app 서비스 DB, 주식 추천 데이터 저장 (recommendations 테이블)
# ──────────────────────────────────────────────────────────────────────────────

# ── DB Subnet Group ───────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "service" {
  name        = "financial-vpc1-db-subnet-group"
  description = "DB subnet group for financial-service RDS"
  subnet_ids  = [aws_subnet.db_a.id, aws_subnet.db_b.id]

  tags = {
    Name = "financial-vpc1-db-subnet-group"
  }
}

# ── Parameter Group ───────────────────────────────────────────────────────────

resource "aws_db_parameter_group" "service" {
  name        = "financial-vpc1-pg16"
  family      = "postgres16"
  description = "PostgreSQL 16 parameter group for financial-service"

  tags = {
    Name = "financial-vpc1-pg16"
  }
}

# ── RDS Instance ──────────────────────────────────────────────────────────────


resource "aws_db_instance" "service" {
  identifier = "financial-service-db"

  engine         = "postgres"
  engine_version = "16"

  instance_class = var.rds_instance_class
  multi_az       = var.rds_multi_az

  db_name  = "financial_service"
  username = "financial_admin"
  password = var.rds_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.service.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.service.name

  allocated_storage = 100
  storage_type      = "gp3"
  storage_encrypted = true

  backup_retention_period = 0
  backup_window           = "18:00-19:00"
  maintenance_window      = "sun:19:00-sun:20:00"

  auto_minor_version_upgrade = false
  deletion_protection        = false
  skip_final_snapshot        = true

  performance_insights_enabled = true

  tags = {
    Name = "financial-service-db"
  }
}
