terraform {
  backend "s3" {
    bucket       = "ilpumjinro-terraform-state"
    key          = "global/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }

  required_version = ">= 1.11.0"
}