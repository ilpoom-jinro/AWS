variable "aws_region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "vpc_cidr" {
  description = "VPC 4 CIDR"
  type        = string
  default     = "10.40.0.0/16"
}
