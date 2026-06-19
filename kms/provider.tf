provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  default = "ap-northeast-2"
}

data "aws_caller_identity" "current" {}
