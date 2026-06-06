# IAM 그룹 생성
# 사람을 직접 관리하는 대신 그룹에 권한을 붙이고 사람을 그룹에 넣는 방식

resource "aws_iam_group" "infra_admin" {
  name = "infra-admin"
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_group" "security_engineers" {
  name = "security-engineers"
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_group" "platform_engineers" {
  name = "platform-engineers"
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_group" "sre_engineers" {
  name = "sre-engineers"
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_group" "onfrem_engineers" {
  name = "onfrem-engineers"
  lifecycle {
    prevent_destroy = true
  }
}

# MAS(Multi-Agent System) 팀 그룹
resource "aws_iam_group" "mas" {
  name = "mas"
  lifecycle {
    prevent_destroy = true
  }
}
