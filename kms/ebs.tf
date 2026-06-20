# =============================================
# EBS 기본 암호화 (#30 / #29 EBS 전수 암호화)
# 계정·리전 단위로 신규 EBS 볼륨을 자동 암호화, 기본 키 = key-eks(CMK)
# kms/에 두는 이유: persistent state라 destroy/apply 사이클에서도 항상 ON,
# 볼륨 생성 전에 기본값이 잡혀서 CSI·비-EKS 볼륨도 자동으로 key-eks를 씀
# =============================================

# 기본 암호화에 쓸 CMK를 key-eks로 지정 (key_eks는 이 모듈에 있으므로 직접 참조)
resource "aws_ebs_default_kms_key" "this" {
  key_arn = aws_kms_key.key_eks.arn
}

# 계정/리전 EBS 기본 암호화 활성화
# 기본 키가 먼저 지정된 뒤 켜지도록 의존성 설정 (관리형 키로 켜지는 순간 방지)
resource "aws_ebs_encryption_by_default" "this" {
  enabled    = true
  depends_on = [aws_ebs_default_kms_key.this]
}