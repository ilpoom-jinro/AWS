# ─────────────────────────────────────
# EC2 SSM IAM Role
# EC2가 SSM Session Manager를 통해 접속 가능하도록
# ─────────────────────────────────────
resource "aws_iam_role" "ec2_ssm" {
  name        = "ilpumjinro-ec2-ssm-role"
  description = "IAM Role for EC2 SSM Session Manager access (no SSH)"

  # EC2 서비스가 이 Role을 사용할 수 있도록 신뢰 정책 설정
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name      = "ilpumjinro-ec2-ssm-role"
    ManagedBy = "terraform"
  }
}

# ─────────────────────────────────────
# AWS 관리형 정책 연결
# SSM 연결 / 세션 열기 / 명령 수신에 필요한 권한 포함
# ─────────────────────────────────────
resource "aws_iam_role_policy_attachment" "ec2_ssm_core" {
  role       = aws_iam_role.ec2_ssm.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ─────────────────────────────────────
# Instance Profile
# EC2는 Role을 직접 받을 수 없어서 Instance Profile로 감싸야 함
# EC2 생성 시 iam_instance_profile에 이 이름 사용
# ─────────────────────────────────────
resource "aws_iam_instance_profile" "ec2_ssm" {
  name = "ilpumjinro-ec2-ssm-profile"
  role = aws_iam_role.ec2_ssm.name

  tags = {
    Name      = "ilpumjinro-ec2-ssm-profile"
    ManagedBy = "terraform"
  }
}

# ─────────────────────────────────────
# Output
# ─────────────────────────────────────
output "ec2_ssm_instance_profile_name" {
  description = "Step 7 ec2.tf > iam_instance_profile 에 등록할 값"
  value       = aws_iam_instance_profile.ec2_ssm.name
}
