output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = [aws_subnet.public_a.id, aws_subnet.public_b.id]
}

output "private_subnet_ids" {
  value = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

output "db_subnet_ids" {
  value = [aws_subnet.db_a.id, aws_subnet.db_b.id]
}

output "public_route_table_id" {
  value = aws_route_table.public.id
}

output "private_route_table_id" {
  value = aws_route_table.private.id
}

output "db_route_table_id" {
  value = aws_route_table.db.id
}

output "alb_sg_id" {
  value = aws_security_group.alb.id
}

output "eks_node_sg_id" {
  value = aws_security_group.eks_node.id
}

output "rds_sg_id" {
  value = aws_security_group.rds.id
}

output "eks_cluster_name" {
  value = aws_eks_cluster.service.name
}

output "eks_cluster_arn" {
  value = aws_eks_cluster.service.arn
}

output "eks_cluster_endpoint" {
  value = aws_eks_cluster.service.endpoint
}

output "eks_cluster_security_group_id" {
  value = aws_eks_cluster.service.vpc_config[0].cluster_security_group_id
}

output "eks_node_group_name" {
  value = aws_eks_node_group.service.node_group_name
}

output "eks_node_role_arn" {
  value = aws_iam_role.eks_node.arn
}

output "rds_endpoint" {
  description = "financial-service RDS 엔드포인트"
  value       = aws_db_instance.service.endpoint
}

output "rds_port" {
  description = "financial-service RDS 포트"
  value       = aws_db_instance.service.port
}

output "rds_db_name" {
  description = "financial-service RDS DB 이름"
  value       = aws_db_instance.service.db_name
}
