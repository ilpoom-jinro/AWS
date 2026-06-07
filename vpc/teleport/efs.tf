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

resource "aws_efs_file_system" "teleport" {
  encrypted = true

  tags = {
    Name = "financial-vpc3-teleport-data"
  }
}

resource "aws_efs_mount_target" "teleport_a" {
  file_system_id  = aws_efs_file_system.teleport.id
  subnet_id       = aws_subnet.private_a.id
  security_groups = [aws_security_group.efs.id]
}
