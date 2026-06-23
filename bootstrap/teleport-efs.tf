# ──────────────────────────────────────────────────────────────────────────────
# Teleport EFS 파일시스템
# terraform destroy vpc/teleport 에서 데이터를 보호하기 위해 bootstrap 에 분리
#
# 마운트 타겟(aws_efs_mount_target)은 VPC 레이어 리소스이므로 vpc/teleport/ 에 유지
# vpc/teleport/ 에서는 data source 로 이 파일시스템을 참조
#
# 주의: 기존 EFS 가 이미 존재한다면 코드 변경 전 반드시 state mv 를 먼저 실행
#   terraform state mv \
#     -state=../vpc/teleport/terraform.tfstate \
#     -state-out=terraform.tfstate \
#     aws_efs_file_system.teleport \
#     aws_efs_file_system.teleport
# ──────────────────────────────────────────────────────────────────────────────
resource "aws_efs_file_system" "teleport" {
  encrypted = true

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name               = "financial-vpc3-teleport-data"
    DataClassification = "Restricted"
  }
}
