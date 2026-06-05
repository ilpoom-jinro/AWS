variable "aws_region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "vpc_cidr" {
  description = "VPC 3 CIDR"
  type        = string
  default     = "10.30.0.0/16"
}

variable "vpc1_cidr" {
  description = "VPC 1 CIDR - for Security Group rules"
  type        = string
  default     = "10.10.0.0/16"
}

variable "vpc2_cidr" {
  description = "VPC 2 CIDR - for Security Group rules"
  type        = string
  default     = "10.20.0.0/16"
}
variable "teleport_ami_id" {
  description = "Packer로 빌드한 Teleport + K3s AMI ID"
  type        = string
  default     = "ami-045f6d48c567e98f8"
}

variable "teleport_allowed_client_cidrs" {
  description = "Client CIDR blocks allowed to reach the Teleport proxy directly when a network path exists"
  type        = list(string)
  default     = []
}
