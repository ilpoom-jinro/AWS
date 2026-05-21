module "iam" {
  source = "./iam"
}

module "vpc1" {
  source = "./vpc/globalservice"
}

module "vpc2" {
  source = "./vpc/ops"
}

module "vpc3" {
  source = "./vpc/teleport"
}

module "vpc4" {
  source = "./vpc/headscale"
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

