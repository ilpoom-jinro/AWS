terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
    # slack-broker.tf의 Lambda 소스 zip 패키징(archive_file)에 필요
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}