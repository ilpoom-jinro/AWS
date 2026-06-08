module "iam" {
  source   = "./iam"
  dev_mode = var.dev_mode
}

module "security" {
  source = "./security"
}

module "vpc1" {
  source          = "./vpc/globalservice"
  rds_password    = random_password.service_rds.result
  kms_key_rds_arn = aws_kms_key.key_rds_globalservice.arn # KMS CMK ARN 연결 - aws/rds 기본키 대신 CMK 사용
  depends_on      = [time_sleep.kms_rds_propagation]      # KMS 전파 완료 후 VPC 모듈 실행
}

module "vpc2" {
  source          = "./vpc/ops"
  rds_password    = random_password.ops_rds.result
  kms_key_rds_arn = aws_kms_key.key_rds_ops.arn      # KMS CMK ARN 연결 - aws/rds 기본키 대신 CMK 사용
  depends_on      = [time_sleep.kms_rds_propagation] # KMS 전파 완료 후 VPC 모듈 실행
}

module "vpc3" {
  source = "./vpc/teleport"

  eks_endpoint = module.vpc2.eks_cluster_endpoint
  eks_ca_data  = module.vpc2.eks_cluster_ca_data
}

module "vpc4" {
  source                 = "./vpc/headscale"
  gcp_fixed_ip           = var.gcp_fixed_ip
  oci_headscale_ip       = var.oci_headscale_ip
  oci_headscale_ip_plain = var.oci_headscale_ip_plain
  tailscale_auth_key     = var.tailscale_auth_key
}

module "vpc_peering" {
  source = "./vpc/peering"

  # VPC ID
  vpc1_id = module.vpc1.vpc_id
  vpc2_id = module.vpc2.vpc_id
  vpc3_id = module.vpc3.vpc_id
  vpc4_id = module.vpc4.vpc_id

  # VPC CIDR
  vpc1_cidr = module.vpc1.vpc_cidr
  vpc2_cidr = module.vpc2.vpc_cidr
  vpc3_cidr = module.vpc3.vpc_cidr
  vpc4_cidr = module.vpc4.vpc_cidr

  # VPC 1 라우팅 테이블 ID
  vpc1_public_rt_id  = module.vpc1.public_route_table_id
  vpc1_private_rt_id = module.vpc1.private_route_table_id
  vpc1_db_rt_id      = module.vpc1.db_route_table_id

  # VPC 2 라우팅 테이블 ID
  vpc2_private_rt_id = module.vpc2.private_route_table_id
  vpc2_db_rt_id      = module.vpc2.db_route_table_id

  # VPC 3 라우팅 테이블 ID
  vpc3_private_rt_id = module.vpc3.private_route_table_id

  # VPC 4 라우팅 테이블 ID
  vpc4_public_rt_id = module.vpc4.public_route_table_id
}

