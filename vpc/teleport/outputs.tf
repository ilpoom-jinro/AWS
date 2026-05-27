output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "private_subnet_ids" {
  value = [aws_subnet.private_a.id]
}

output "private_route_table_id" {
  value = aws_route_table.private.id
}

output "teleport_sg_id" {
  value = aws_security_group.teleport.id
}

output "teleport_instance_id" {
  value = aws_instance.teleport.id
}

output "teleport_ec2_role_name" {
  description = "Teleport EC2 IAM Role 이름"
  value       = aws_iam_role.teleport_ec2.name
}
