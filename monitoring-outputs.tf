output "ops_aws_load_balancer_controller_role_arn" {
  description = "IAM role ARN used by the AWS Load Balancer Controller in the Ops EKS cluster"
  value       = module.vpc2.aws_load_balancer_controller_role_arn
}

output "ops_vpc_id" {
  description = "VPC ID of the isolated Ops VPC"
  value       = module.vpc2.vpc_id
}

output "ops_elasticloadbalancing_vpc_endpoint_id" {
  description = "Interface VPC endpoint used by the Ops VPC to call the ELB API"
  value       = module.vpc2.elasticloadbalancing_vpc_endpoint_id
}

output "ops_loki_nlb_sg_id" {
  description = "Security group ID to insert into the Loki internal NLB Service values"
  value       = module.vpc2.loki_nlb_sg_id
}

output "ops_thanos_receive_nlb_sg_id" {
  description = "Security group ID to insert into the Thanos Receive internal NLB Service values"
  value       = module.vpc2.thanos_receive_nlb_sg_id
}

output "service_xray_collector_role_arn" {
  description = "IAM role ARN used by the Service EKS ADOT Collector through Pod Identity"
  value       = module.vpc1.xray_collector_role_arn
}

output "ops_grafana_cloudwatch_role_arn" {
  description = "IAM role ARN used by the Ops EKS Grafana Pod through Pod Identity"
  value       = module.vpc2.grafana_cloudwatch_role_arn
}
