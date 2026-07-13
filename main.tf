module "iam" {
  source   = "./iam"
  dev_mode = var.dev_mode
}

module "security" {
  source                  = "./security"
  kms_key_cloudtrail_arn  = data.aws_kms_key.key_cloudtrail.arn
  account_id              = data.aws_caller_identity.current.account_id
  key_s3_arn              = data.aws_kms_key.key_s3.arn
  key_sns_arn             = data.aws_kms_key.key_sns.arn
  enable_pii_scan         = var.enable_pii_scan
  pii_scan_target_buckets = var.pii_scan_target_buckets
  pii_scan_ecr_image      = "${aws_ecr_repository.pii_scan.repository_url}:latest"
  pii_scan_ecr_repo_arn   = aws_ecr_repository.pii_scan.arn
  # SIEM Athena results 버킷 이름 suffix용 (security/siem-athena.tf)
  aws_region = var.aws_region

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }
}

module "vpc1" {
  source                     = "./vpc/globalservice"
  rds_password               = random_password.service_rds.result
  kms_key_rds_arn            = data.aws_kms_key.key_rds_globalservice.arn
  kms_key_eks_arn            = data.aws_kms_key.key_eks.arn
  kms_key_secretsmanager_arn = data.aws_kms_key.key_secretsmanager.arn
  account_id                 = data.aws_caller_identity.current.account_id
  single_az_mode             = var.single_az_mode
  rds_backup_retention       = var.rds_backup_retention

  # providers 인자를 쓰면 default aws 상속이 취소되므로 aws도 명시적으로 전달.
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }
}

module "vpc2" {
  source                     = "./vpc/ops"
  rds_password               = random_password.ops_rds.result
  kms_key_rds_arn            = data.aws_kms_key.key_rds_ops.arn
  kms_key_eks_arn            = data.aws_kms_key.key_eks.arn
  kms_key_secretsmanager_arn = data.aws_kms_key.key_secretsmanager.arn
  kms_key_s3_arn             = data.aws_kms_key.key_s3.arn
  account_id                 = data.aws_caller_identity.current.account_id
  single_az_mode             = var.single_az_mode
  rds_backup_retention       = var.rds_backup_retention

  # slack-hitl 봇 Pod Identity role(vpc/ops/pod-identity.tf)에 큐 ARN 스코프를 넘기기 위함
  # — 큐 자체는 루트 slack-broker.tf 리소스라 모듈 경계를 변수로 넘어야 함.
  slack_hitl_inbound_queue_arn  = aws_sqs_queue.slack_hitl_inbound.arn
  slack_hitl_outbound_queue_arn = aws_sqs_queue.slack_hitl_outbound.arn

  depends_on = [module.iam] # mas-policy가 먼저 생성된 후 policy attachment 실행

  # providers 인자를 쓰면 default aws 상속이 취소되므로 aws도 명시적으로 전달.
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }
}

module "vpc3" {
  source = "./vpc/teleport"

  eks_endpoint            = module.vpc2.eks_cluster_endpoint
  eks_ca_data             = module.vpc2.eks_cluster_ca_data
  teleport_app_join_token = random_password.teleport_app_join_token.result
}

module "vpc4" {
  source                 = "./vpc/headscale"
  gcp_fixed_ip           = var.gcp_fixed_ip
  oci_headscale_ip       = var.oci_headscale_ip
  oci_headscale_ip_plain = var.oci_headscale_ip_plain
  headscale_login_server = var.headscale_login_server
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
