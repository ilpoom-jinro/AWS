resource "random_password" "temporal_db" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "temporal" {
  name       = var.temporal_db_subnet_group_name
  subnet_ids = [aws_subnet.db_a.id, aws_subnet.db_b.id]

  tags = {
    Name      = var.temporal_db_subnet_group_name
    Purpose   = "temporal-persistence"
    ManagedBy = "terraform"
  }
}

resource "aws_db_parameter_group" "temporal" {
  name   = var.temporal_db_parameter_group_name
  family = var.temporal_db_parameter_group_family

  parameter {
    name  = "rds.force_ssl"
    value = "0"
  }

  tags = {
    Name      = var.temporal_db_parameter_group_name
    Purpose   = "temporal-persistence"
    ManagedBy = "terraform"
  }
}

resource "aws_db_instance" "temporal" {
  identifier = var.temporal_db_identifier

  engine         = "postgres"
  engine_version = var.temporal_db_engine_version
  instance_class = var.temporal_db_instance_class

  allocated_storage     = var.temporal_db_allocated_storage
  max_allocated_storage = var.temporal_db_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.temporal_db_name
  username = var.temporal_db_username
  password = random_password.temporal_db.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.temporal.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.temporal.name

  multi_az                = var.temporal_db_multi_az
  publicly_accessible    = false
  backup_retention_period = var.temporal_db_backup_retention_period
  backup_window           = var.temporal_db_backup_window
  maintenance_window      = var.temporal_db_maintenance_window

  deletion_protection = var.temporal_db_deletion_protection
  skip_final_snapshot       = var.temporal_db_skip_final_snapshot
  final_snapshot_identifier = "${var.temporal_db_identifier}-final"

  tags = {
    Name      = var.temporal_db_identifier
    Purpose   = "temporal-persistence"
    ManagedBy = "terraform"
  }
}

resource "aws_secretsmanager_secret" "temporal_db" {
  name                    = var.temporal_db_secret_name
  description             = "Temporal PostgreSQL connection settings for the Ops EKS cluster"
  recovery_window_in_days = 7

  tags = {
    Name      = var.temporal_db_secret_name
    Purpose   = "temporal-persistence"
    ManagedBy = "terraform"
  }
}

resource "aws_secretsmanager_secret_version" "temporal_db" {
  secret_id = aws_secretsmanager_secret.temporal_db.id

  secret_string = jsonencode({
    host     = aws_db_instance.temporal.address
    port     = aws_db_instance.temporal.port
    dbname   = var.temporal_db_name
    username = var.temporal_db_username
    password = random_password.temporal_db.result
  })
}
