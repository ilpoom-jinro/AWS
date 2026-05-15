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
}

module "vpc_peering" {
  source = "./vpc/peering"

  vpc1_id   = module.vpc1.vpc_id
  vpc2_id   = module.vpc2.vpc_id
  vpc3_id   = module.vpc3.vpc_id
  vpc4_id   = module.vpc4.vpc_id

  vpc1_cidr = module.vpc1.vpc_cidr
  vpc2_cidr = module.vpc2.vpc_cidr
  vpc3_cidr = module.vpc3.vpc_cidr
  vpc4_cidr = module.vpc4.vpc_cidr
}
