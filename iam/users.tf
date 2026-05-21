# =============================================
# IAM 사용자 5명 생성
# =============================================

# 인프라 담당
resource "aws_iam_user" "infra" {
  name = "infra"
  tags = {
    Project   = "ilpumjinro"
    ManagedBy = "terraform"
    Owner     = "infra"
  }
  lifecycle {
    prevent_destroy = true
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
  lifecycle {
    prevent_destroy = true
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
  lifecycle {
    prevent_destroy = true
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
  lifecycle {
    prevent_destroy = true
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
  lifecycle {
    prevent_destroy = true
  }
}

# =============================================
# 사용자 → 그룹 배정
# =============================================

resource "aws_iam_user_group_membership" "infra" {
  user   = aws_iam_user.infra.name
  groups = [aws_iam_group.infra_admin.name]
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
