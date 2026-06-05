output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "private_subnet_ids" {
  value = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

output "db_subnet_ids" {
  value = [aws_subnet.db_a.id, aws_subnet.db_b.id]
}

output "private_route_table_id" {
  value = aws_route_table.private.id
}

output "db_route_table_id" {
  value = aws_route_table.db.id
}

output "eks_node_sg_id" {
  value = aws_security_group.eks_node.id
}

output "rds_sg_id" {
  value = aws_security_group.rds.id
}

output "eks_cluster_name" {
  value = aws_eks_cluster.ops.name
}

output "eks_cluster_arn" {
  value = aws_eks_cluster.ops.arn
}

output "eks_cluster_endpoint" {
  value = aws_eks_cluster.ops.endpoint
}

output "eks_cluster_ca_data" {
  value = aws_eks_cluster.ops.certificate_authority[0].data
}

output "eks_cluster_security_group_id" {
  value = aws_eks_cluster.ops.vpc_config[0].cluster_security_group_id
}

output "eks_node_group_name" {
  value = aws_eks_node_group.ops.node_group_name
}

output "eks_node_role_arn" {
  value = aws_iam_role.eks_node.arn
}

output "monitor_subnet_id" {
  description = "monitoring only subnet ID"
  value       = aws_subnet.monitor_a.id
}

output "monitor_subnet_cidr" {
  description = "monitoring only subnet CIDR"
  value       = aws_subnet.monitor_a.cidr_block
}

output "rds_endpoint" {
  description = "financial-ops RDS 엔드포인트"
  value       = aws_db_instance.ops.endpoint
}

output "rds_port" {
  description = "financial-ops RDS 포트"
  value       = aws_db_instance.ops.port
}

output "rds_db_name" {
  description = "financial-ops RDS DB 이름"
  value       = aws_db_instance.ops.db_name
}

output "rds_secret_arn" {
  description = "financial-ops RDS 비밀번호 Secrets Manager ARN"
  value       = aws_secretsmanager_secret.rds_password.arn
}
