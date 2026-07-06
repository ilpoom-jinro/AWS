terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
      # SAR 앱이 us-east-1에만 게시돼 있어, rotation data source를
      # us-east-1 provider로 조회하기 위한 alias 선언.
      configuration_aliases = [aws.us_east_1]
    }
  }
}
