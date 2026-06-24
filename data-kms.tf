# =============================================
# KMS CMK data source 참조
# 실제 리소스는 kms/ 모듈에서 관리 (별도 state)
# 참조는 data.aws_kms_key.<name>.arn 으로
# =============================================

data "aws_kms_alias" "key_rds_ops" {
  name = "alias/key-rds-ops"
}
data "aws_kms_key" "key_rds_ops" {
  key_id = data.aws_kms_alias.key_rds_ops.target_key_id
}

data "aws_kms_alias" "key_rds_globalservice" {
  name = "alias/key-rds-globalservice"
}
data "aws_kms_key" "key_rds_globalservice" {
  key_id = data.aws_kms_alias.key_rds_globalservice.target_key_id
}

data "aws_kms_alias" "key_cloudtrail" {
  name = "alias/key-cloudtrail"
}
data "aws_kms_key" "key_cloudtrail" {
  key_id = data.aws_kms_alias.key_cloudtrail.target_key_id
}

data "aws_kms_alias" "key_s3" {
  name = "alias/key-s3"
}
data "aws_kms_key" "key_s3" {
  key_id = data.aws_kms_alias.key_s3.target_key_id
}

data "aws_kms_alias" "key_secretsmanager" {
  name = "alias/key-secretsmanager"
}
data "aws_kms_key" "key_secretsmanager" {
  key_id = data.aws_kms_alias.key_secretsmanager.target_key_id
}

data "aws_kms_alias" "key_eks" {
  name = "alias/key-eks"
}
data "aws_kms_key" "key_eks" {
  key_id = data.aws_kms_alias.key_eks.target_key_id
}

data "aws_kms_alias" "key_logs" {
  name = "alias/key-logs"
}
data "aws_kms_key" "key_logs" {
  key_id = data.aws_kms_alias.key_logs.target_key_id
}

data "aws_kms_alias" "key_sns" {
  name = "alias/key-sns"
}
data "aws_kms_key" "key_sns" {
  key_id = data.aws_kms_alias.key_sns.target_key_id
}
