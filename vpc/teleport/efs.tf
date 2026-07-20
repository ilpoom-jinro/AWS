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
  # destroy 시 teleport_efs_id_override가 주어지면 이 조회를 건너뛴다.
  # EFS가 이미 사라진 상태에서는 태그 조회 자체가 실패해 plan이 막히기 때문.
  count = var.teleport_efs_id_override == null ? 1 : 0
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
  file_system_id  = coalesce(var.teleport_efs_id_override, try(data.aws_efs_file_system.teleport[0].id, null))
  subnet_id       = aws_subnet.private_a.id
  security_groups = [aws_security_group.efs.id]
}
