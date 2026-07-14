# ──────────────────────────────────────────────────────────────────────────────
# VPC 2 — VPC Endpoints (망분리 핵심)
#
# IGW/NAT 없이 AWS API 접근을 위한 VPC Endpoint 구성
# 모든 트래픽이 AWS 내부 백본망만 통과 (인터넷 구간 없음)
# ──────────────────────────────────────────────────────────────────────────────

# Interface Endpoint ENI 배치 AZ - single_az_mode = true 시 비용 절감을 위해 AZ-a에만 배치
locals {
  endpoint_subnet_ids            = var.single_az_mode ? [aws_subnet.private_a.id] : [aws_subnet.private_a.id, aws_subnet.private_b.id]
  eks_bootstrap_endpoint_subnets = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

# ── Endpoint 전용 Security Group ──────────────────────────────────────────────
# VPC 2 내부에서 443 포트만 허용
# VPC 3 Teleport에서 SSH(22) 허용 (관리 목적)

resource "aws_security_group" "endpoints" {
  name        = "financial-vpc2-endpoint-sg"
  description = "Security Group for VPC Endpoints - Allow HTTPS from within VPC 2"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Allow HTTPS from within VPC 2"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "financial-vpc2-endpoint-sg"
  }
}

# ── Gateway Endpoints  ───────────────────────────────────────────────────────

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"

  route_table_ids = [
    aws_route_table.private.id,
    aws_route_table.db.id,
  ]

  tags = {
    Name = "financial-vpc2-endpoint-s3"
  }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"

  route_table_ids = [
    aws_route_table.private.id,
    aws_route_table.db.id,
  ]

  tags = {
    Name = "financial-vpc2-endpoint-dynamodb"
  }
}

# ── Interface Endpoints (PrivateLink, ENI 생성) ────────────────────────────────

# ECR — 컨테이너 이미지 풀
resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.eks_bootstrap_endpoint_subnets
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-ecr-api"
  }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.eks_bootstrap_endpoint_subnets
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-ecr-dkr"
  }
}

# EKS — Control Plane 통신
resource "aws_vpc_endpoint" "eks" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.eks"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.eks_bootstrap_endpoint_subnets
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-eks"
  }
}

# CloudWatch Logs
resource "aws_vpc_endpoint" "logs" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-logs"
  }
}

# CloudWatch Metrics
resource "aws_vpc_endpoint" "monitoring" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.monitoring"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-monitoring"
  }
}

# Athena API used by the FinOps Cost Agent to query CUR data privately.
resource "aws_vpc_endpoint" "athena" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.athena"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-athena"
  }
}

# SSM Systems Manager endpoint.
resource "aws_vpc_endpoint" "ssm" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-ssm"
  }
}

resource "aws_vpc_endpoint" "ssmmessages" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-ssmmessages"
  }
}

resource "aws_vpc_endpoint" "ec2messages" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ec2messages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-ec2messages"
  }
}

# Secrets Manager — 민감 정보 관리
resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-secretsmanager"
  }
}

# KMS — 암호화 키 관리
resource "aws_vpc_endpoint" "kms" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.kms"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-kms"
  }
}

# STS — IAM 임시 자격증명 (EKS IRSA, EC2 Instance Profile)
resource "aws_vpc_endpoint" "sts" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.sts"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.eks_bootstrap_endpoint_subnets
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-sts"
  }
}

# EC2 — EKS 노드 그룹 API 통신
resource "aws_vpc_endpoint" "ec2" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ec2"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.eks_bootstrap_endpoint_subnets
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-ec2"
  }
}

# RDS API endpoint for private CodeBuild jobs that discover DB endpoints.
resource "aws_vpc_endpoint" "rds" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.rds"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-rds"
  }
}

# EKS Auth
resource "aws_vpc_endpoint" "eks_auth" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.eks-auth"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.eks_bootstrap_endpoint_subnets
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-eks-auth"
  }
}

# Bedrock Runtime — finops-mas 에이전트가 InvokeModel(Claude)을 호출하는 PrivateLink 통로.
# VPC2는 IGW/NAT 없는 망분리 환경이므로 이 endpoint 없이는 Bedrock 호출 불가.
# (#4 안전한 네트워크 경로)
resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-bedrock-runtime"
  }
}

# Bedrock Agent Runtime — SecOps 에이전트가 Knowledge Base retrieve(RAG 규정 검색)를
# 호출하는 PrivateLink 통로. bedrock-runtime(InvokeModel)과는 별개 서비스라
# 별도 endpoint 필요. VPC2는 IGW/NAT 없는 망분리 환경이므로 이 endpoint 없이는
# KB retrieve 호출 불가. (#4 안전한 네트워크 경로)
resource "aws_vpc_endpoint" "bedrock_agent_runtime" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-agent-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-bedrock-agent-runtime"
  }
}

# Bedrock API endpoint for model metadata and non-runtime Bedrock calls.
resource "aws_vpc_endpoint" "bedrock" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-bedrock"
  }
}

# ── SQS Interface Endpoint ────────────────────────────────────────────────────
# SecOps 워커(in-cluster poller)가 격리망에서 트리거 SQS 큐를 폴링하기 위함.
# (secops-trigger.tf: GuardDuty→EventBridge→SQS→워커). 엔드포인트가 없으면
# 워커의 SQS 호출이 connect timeout — wafv2 때와 동일 격리망 제약.
resource "aws_vpc_endpoint" "sqs" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.sqs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-sqs"
  }
}
