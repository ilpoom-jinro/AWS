terraform {
  backend "s3" {
    bucket       = "ilpumjinro-terraform-state-v4"
    key          = "global/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    kms_key_id   = "alias/key-s3"
    use_lockfile = true
  }

  required_version = ">= 1.11.0"
}