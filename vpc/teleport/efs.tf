# ──────────────────────────────────────────────────────────────────────────────
# EFS 마운트 타겟 및 보안 그룹
#
# EFS 파일시스템 자체(aws_efs_file_system)는 bootstrap/teleport-efs.tf 에서 관리
# destroy 보호를 위해 분리되었으며, 여기서는 data source 로 참조
#
# 마운트 타겟과 SG 는 VPC 리소스에 의존하므로 이 모듈에 유지
# vpc/teleport 를 destroy 하더라도 EFS 데이터는 보존됨
# ──────────────────────────────────────────────────────────────────────────────

data "aws_efs_file_system" "teleport" {
  tags = {
    Name = "financial-vpc3-teleport-data"
  }
}

resource "aws_security_group" "efs" {
  name        = "financial-vpc3-efs-sg"
  description = "EFS Security Group - Allow NFS from Teleport EC2"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Allow NFS from Teleport EC2"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.teleport.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "financial-vpc3-efs-sg"
  }
}

resource "aws_efs_mount_target" "teleport_a" {
  file_system_id  = data.aws_efs_file_system.teleport.id
  subnet_id       = aws_subnet.private_a.id
  security_groups = [aws_security_group.efs.id]
}
