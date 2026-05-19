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

output "headscale_router_eip" {
  description = "Tailscale Router EC2 Elastic IP (OCI Headscale 등록 주소)"
  value       = aws_eip.headscale_router.public_ip
}
