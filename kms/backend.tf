terraform {
  backend "s3" {
    bucket       = "ilpumjinro-terraform-state-v4"
    key          = "kms/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }

  required_version = ">= 1.11.0"
}
