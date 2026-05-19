output "vpc1_id"   { value = aws_vpc.vpc1_service.id }
output "vpc1_cidr" { value = aws_vpc.vpc1_service.cidr_block }

output "vpc2_id"   { value = aws_vpc.vpc2_ops.id }
output "vpc2_cidr" { value = aws_vpc.vpc2_ops.cidr_block }

output "vpc3_id"   { value = aws_vpc.vpc3_teleport.id }
output "vpc3_cidr" { value = aws_vpc.vpc3_teleport.cidr_block }

output "vpc4_id"   { value = aws_vpc.vpc4_headscale.id }
output "vpc4_cidr" { value = aws_vpc.vpc4_headscale.cidr_block }
