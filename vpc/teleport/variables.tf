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
variable "eks_endpoint" {
  description = "VPC2 EKS 클러스터 API 서버 엔드포인트"
  type        = string
}

variable "eks_ca_data" {
  description = "VPC2 EKS 클러스터 CA 인증서 데이터 (base64)"
  type        = string
}

variable "teleport_efs_id_override" {
  description = "teleport EFS ID data source 조회 우회값. destroy 시 EFS가 이미 없으면 태그 조회가 실패해 plan이 막히므로, 그 경우에만 임의 문자열을 넘겨 조회를 건너뛴다."
  type        = string
  default     = null
}

variable "teleport_ami_id_override" {
  description = "teleport EC2 AMI data source 조회 우회값. destroy 시 Packer AMI가 이미 없으면 조회가 실패해 plan이 막히므로, 그 경우에만 임의 값을 넘겨 조회를 건너뛴다."
  type        = string
  default     = null
}
