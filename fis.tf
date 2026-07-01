# ──────────────────────────────────────────────────────────────────────────────
# AWS FIS (Fault Injection Simulator) — 카오스 엔지니어링 실험 정의
# (A) 정의 전용: apply·실행 안 함
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# FIS IAM Role
# principal: fis.amazonaws.com / confused deputy 방지용 SourceAccount 조건 포함
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "fis" {
  name = "financial-fis-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "fis.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:fis:${var.aws_region}:${data.aws_caller_identity.current.account_id}:experiment/*"
        }
      }
    }]
  })

  tags = {
    Name = "financial-fis-role"
  }
}

resource "aws_iam_role_policy" "fis" {
  name = "financial-fis-policy"
  role = aws_iam_role.fis.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EKSNodeTermination"
        Effect = "Allow"
        Action = [
          "ec2:TerminateInstances",
          "ec2:DescribeInstances",
          "autoscaling:DescribeAutoScalingGroups",
          "eks:DescribeNodegroup",
        ]
        Resource = "*"
      },
      {
        Sid    = "RDSReboot"
        Effect = "Allow"
        Action = [
          "rds:RebootDBInstance",
          "rds:DescribeDBInstances",
        ]
        Resource = "*"
      },
    ]
  })
}

# ──────────────────────────────────────────────────────────────────────────────
# 실험 템플릿 1 — EKS Service 노드그룹 인스턴스 강제 종료
# cluster: financial-service-eks / nodegroup: financial-service-eks-general
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_fis_experiment_template" "eks_service" {
  description = "Service EKS 노드그룹 인스턴스 100% 강제 종료 — ASG 자동 복구 및 워크로드 재스케줄 검증"
  role_arn    = aws_iam_role.fis.arn

  stop_condition {
    source = "none"
  }

  action {
    name      = "terminate-service-nodegroup-instances"
    action_id = "aws:eks:terminate-nodegroup-instances"

    parameter {
      key   = "instanceTerminationPercentage"
      value = "100"
    }

    target {
      key   = "Nodegroups"
      value = "service-eks-general-target"
    }
  }

  target {
    name           = "service-eks-general-target"
    resource_type  = "aws:eks:nodegroup"
    selection_mode = "COUNT(1)"

    resource_tag {
      key   = "Name"
      value = "financial-service-eks-general"
    }
  }

  tags = {
    Name        = "financial-fis-eks-service"
    Environment = "dev"
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# 실험 템플릿 2 — EKS Ops 노드그룹 인스턴스 강제 종료
# cluster: financial-ops-eks / nodegroup: financial-ops-eks-general
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_fis_experiment_template" "eks_ops" {
  description = "Ops EKS 노드그룹 인스턴스 100% 강제 종료 — ArgoCD·Kyverno 등 운영 워크로드 복구 검증"
  role_arn    = aws_iam_role.fis.arn

  stop_condition {
    source = "none"
  }

  action {
    name      = "terminate-ops-nodegroup-instances"
    action_id = "aws:eks:terminate-nodegroup-instances"

    parameter {
      key   = "instanceTerminationPercentage"
      value = "100"
    }

    target {
      key   = "Nodegroups"
      value = "ops-eks-general-target"
    }
  }

  target {
    name           = "ops-eks-general-target"
    resource_type  = "aws:eks:nodegroup"
    selection_mode = "COUNT(1)"

    resource_tag {
      key   = "Name"
      value = "financial-ops-eks-general"
    }
  }

  tags = {
    Name        = "financial-fis-eks-ops"
    Environment = "dev"
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# 실험 템플릿 3 — RDS Service DB 강제 재부팅 (forceFailover)
# identifier: financial-service-db (일반 RDS PostgreSQL 16, aws_db_instance)
# ──────────────────────────────────────────────────────────────────────────────
# 주의: single_az_mode=true 환경에서는 standby AZ가 없어 forceFailover가
# 단순 재부팅으로 동작함. Multi-AZ 전환 후에야 실제 AZ failover 검증 가능.
# (Aurora cluster 아님 — failover-db-cluster action 아닌 reboot-db-instances 사용)
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_fis_experiment_template" "rds_service" {
  description = "Service RDS PostgreSQL forceFailover 재부팅 — Multi-AZ 환경에서 AZ 전환·앱 재연결 검증"
  role_arn    = aws_iam_role.fis.arn

  stop_condition {
    source = "none"
  }

  action {
    name      = "reboot-service-db-instance"
    action_id = "aws:rds:reboot-db-instances"

    parameter {
      key   = "forceFailover"
      value = "true"
    }

    target {
      key   = "DBInstances"
      value = "service-rds-target"
    }
  }

  target {
    name           = "service-rds-target"
    resource_type  = "aws:rds:db"
    selection_mode = "COUNT(1)"

    resource_tag {
      key   = "Name"
      value = "financial-service-db"
    }
  }

  tags = {
    Name        = "financial-fis-rds-service"
    Environment = "dev"
  }
}

# ──────────────────────────────────────────────────────────────────────────────
# 실험 템플릿 4 — RDS Ops DB 강제 재부팅 (forceFailover)
# identifier: financial-ops-db (일반 RDS PostgreSQL 16, aws_db_instance)
# ──────────────────────────────────────────────────────────────────────────────
# 주의: single_az_mode=true 환경에서는 standby AZ가 없어 forceFailover가
# 단순 재부팅으로 동작함. Multi-AZ 전환 후에야 실제 AZ failover 검증 가능.
# (Aurora cluster 아님 — failover-db-cluster action 아닌 reboot-db-instances 사용)
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_fis_experiment_template" "rds_ops" {
  description = "Ops RDS PostgreSQL forceFailover 재부팅 — Multi-AZ 환경에서 AZ 전환·운영 DB 복구 검증"
  role_arn    = aws_iam_role.fis.arn

  stop_condition {
    source = "none"
  }

  action {
    name      = "reboot-ops-db-instance"
    action_id = "aws:rds:reboot-db-instances"

    parameter {
      key   = "forceFailover"
      value = "true"
    }

    target {
      key   = "DBInstances"
      value = "ops-rds-target"
    }
  }

  target {
    name           = "ops-rds-target"
    resource_type  = "aws:rds:db"
    selection_mode = "COUNT(1)"

    resource_tag {
      key   = "Name"
      value = "financial-ops-db"
    }
  }

  tags = {
    Name        = "financial-fis-rds-ops"
    Environment = "dev"
  }
}