variable "aws_region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "vpc_cidr" {
  description = "VPC 2 CIDR"
  type        = string
  default     = "10.20.0.0/16"
}
