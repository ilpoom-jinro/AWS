output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = [aws_subnet.public_a.id]
}

output "public_route_table_id" {
  value = aws_route_table.public.id
}

output "headscale_router_sg_id" {
  value = aws_security_group.headscale_router.id
}

output "headscale_router_instance_id" {
  value = aws_instance.headscale_router.id
}

output "cloudsql_failback_credentials_secret_arn" {
  description = "Failback workflow가 Cloud SQL 및 역복제 자격증명을 전달하는 전용 시크릿 ARN"
  value       = aws_secretsmanager_secret.cloudsql_failback_credentials.arn
}

output "cloudsql_reverse_replication_document_arn" {
  description = "AWS Router에서 Cloud SQL to RDS 역복제를 실행하는 고정 SSM 문서 ARN"
  value       = aws_ssm_document.cloudsql_reverse_replication.arn
}

output "headscale_router_eip" {
  description = "Tailscale Router EC2 Elastic IP (OCI Headscale 등록 주소)"
  value       = aws_eip.headscale_router.public_ip
}
