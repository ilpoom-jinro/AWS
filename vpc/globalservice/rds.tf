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
  # gcp DMS에서 마이그레이션하기 위해 PostgreSQL logical replication 키기 -> AWS RDS가 DMS CDC source가 됨
  parameter {
    name         = "rds.logical_replication"
    value        = "1"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "shared_preload_libraries"
    value        = "pglogical"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "wal_sender_timeout"
    value        = "0"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "max_replication_slots"
    value        = "10"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "max_wal_senders"
    value        = "10"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "max_logical_replication_workers"
    value        = "4"
    apply_method = "pending-reboot"
  }

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
  multi_az       = var.single_az_mode ? false : var.rds_multi_az

  db_name  = "financial_service"
  username = "financial_admin"
  password = var.rds_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.service.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.service.name
  publicly_accessible    = false

  allocated_storage = 100
  storage_type      = "gp3"
  storage_encrypted = true
  kms_key_id        = var.kms_key_rds_arn # KMS CMK ARN 연결 - aws/rds 기본키 대신 CMK 사용

  backup_retention_period  = var.rds_backup_retention # 토글: Free Plan=0(default), Paid=7(tfvars)
  backup_window            = "18:00-19:00"
  maintenance_window       = "sun:19:00-sun:20:00"
  delete_automated_backups = true

  auto_minor_version_upgrade = false
  deletion_protection        = var.deletion_protection
  skip_final_snapshot        = true

  performance_insights_enabled = true

  tags = {
    Name               = "financial-service-db"
    DataClassification = "Confidential"
  }
}
