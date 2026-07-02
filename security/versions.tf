terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
      # 루트에서 us-east-1 provider를 넘겨받기 위한 alias 선언
      configuration_aliases = [aws.us_east_1]
    }
  }
}
