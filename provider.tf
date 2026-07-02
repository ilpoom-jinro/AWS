provider "aws" {
  region = var.aws_region
}

# STS 글로벌 엔드포인트/콘솔 경유 이벤트는 us-east-1에 기록되므로
# EventBridge 탐지 규칙도 us-east-1에 있어야 트리거됨
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

provider "random" {}


variable "aws_region" {
  default = "ap-northeast-2"
}