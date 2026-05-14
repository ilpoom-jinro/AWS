# =============================================
# IAM 사용자 5명 생성
# =============================================

# 인프라 담당
resource "aws_iam_user" "infra" {
  name = "infra"
  tags = {
    Project   = "ilpumjinro" # 프로젝트 식별자
    ManagedBy = "terraform"  # 이 리소스는 Terraform으로 관리됨
    Owner     = "infra"      # 담당 팀
  }
}

# 보안 담당
resource "aws_iam_user" "security" {
  name = "security"
  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "security"
  }
}

# 플랫폼 담당
resource "aws_iam_user" "platform" {
  name = "platform"
  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "platform"
  }
}

# SRE 담당
resource "aws_iam_user" "sre" {
  name = "sre"
  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "sre"
  }
}

# 온프레미스 로그 담당
resource "aws_iam_user" "onfrem" {
  name = "onfrem"
  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "onfrem"
  }
}

# =============================================
# 사용자 → 그룹 배정
# =============================================

resource "aws_iam_user_group_membership" "infra" {
  user   = aws_iam_user.infra.name           # infra 사용자를
  groups = [aws_iam_group.infra_admin.name]  # infra-admin 그룹에 배정
}

resource "aws_iam_user_group_membership" "security" {
  user   = aws_iam_user.security.name
  groups = [aws_iam_group.security_engineers.name]
}

resource "aws_iam_user_group_membership" "platform" {
  user   = aws_iam_user.platform.name
  groups = [aws_iam_group.platform_engineers.name]
}

resource "aws_iam_user_group_membership" "sre" {
  user   = aws_iam_user.sre.name
  groups = [aws_iam_group.sre_engineers.name]
}

resource "aws_iam_user_group_membership" "onfrem" {
  user   = aws_iam_user.onfrem.name
  groups = [aws_iam_group.onfrem_engineers.name]
}