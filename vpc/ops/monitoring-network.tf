# Network resources used by the monitoring stack in the isolated Ops VPC.

# The AWS Load Balancer Controller calls the ELB API through this endpoint.
# This keeps API traffic on the AWS network because the Ops VPC has no NAT GW.
resource "aws_vpc_endpoint" "elasticloadbalancing" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.elasticloadbalancing"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "financial-vpc2-endpoint-elasticloadbalancing"
  }
}

# Attached to the Loki internal NLB by the Kubernetes Service annotation.
# Only Alloy running in the Service VPC EKS private subnets may push logs.
resource "aws_security_group" "loki_nlb" {
  name        = "financial-vpc2-loki-nlb-sg"
  description = "Allow Loki log ingestion from the Service VPC EKS private subnets"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Allow Alloy log push from the Service VPC"
    from_port   = 3100
    to_port     = 3100
    protocol    = "tcp"
    cidr_blocks = var.service_eks_private_subnet_cidrs
  }

  egress {
    description = "Allow Loki NLB traffic to monitoring targets"
    from_port   = 3100
    to_port     = 3100
    protocol    = "tcp"
    cidr_blocks = [aws_subnet.monitor_a.cidr_block]
  }

  tags = {
    Name = "financial-vpc2-loki-nlb-sg"
  }
}

# Attached to the Thanos Receive internal NLB by the Kubernetes Service
# annotation. Only Alloy in the Service VPC may push Prometheus metrics.
resource "aws_security_group" "thanos_receive_nlb" {
  name        = "financial-vpc2-thanos-receive-nlb-sg"
  description = "Allow Thanos Receive ingestion from the Service VPC EKS private subnets"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Allow Alloy metric push from the Service VPC"
    from_port   = 19291
    to_port     = 19291
    protocol    = "tcp"
    cidr_blocks = var.service_eks_private_subnet_cidrs
  }

  egress {
    description = "Allow Thanos Receive NLB traffic to monitoring targets"
    from_port   = 19291
    to_port     = 19291
    protocol    = "tcp"
    cidr_blocks = [aws_subnet.monitor_a.cidr_block]
  }

  tags = {
    Name = "financial-vpc2-thanos-receive-nlb-sg"
  }
}

output "elasticloadbalancing_vpc_endpoint_id" {
  description = "Interface VPC endpoint used to call the ELB API without internet access"
  value       = aws_vpc_endpoint.elasticloadbalancing.id
}

output "loki_nlb_sg_id" {
  description = "Security group ID to attach to the Loki internal NLB"
  value       = aws_security_group.loki_nlb.id
}

output "thanos_receive_nlb_sg_id" {
  description = "Security group ID to attach to the Thanos Receive internal NLB"
  value       = aws_security_group.thanos_receive_nlb.id
}
