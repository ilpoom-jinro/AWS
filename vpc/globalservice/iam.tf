# =============================================
# EKS 클러스터 Role KMS inline 정책
#
# key-eks 키 정책에서 클러스터 Role ARN을 직접 참조하면
# key 생성 시점에 Role이 아직 없어 MalformedPolicyDocumentException 발생.
# key 정책의 EnableRootAccess(kms:*)를 통한 IAM delegation으로 처리:
#   - 키 정책: root kms:* 허용 → IAM 위임 가능
#   - 여기: 클러스터 Role에 KMS 사용 권한 부여
# =============================================

resource "aws_iam_role_policy" "eks_cluster_kms" {
  name = "${var.eks_cluster_name}-kms-policy"
  role = aws_iam_role.eks_cluster.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowEKSSecretsEncryption"
      Effect = "Allow"
      Action = [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:ReEncrypt*",
        "kms:GenerateDataKey*",
        "kms:DescribeKey",
        "kms:CreateGrant" # EKS가 encryption_config 활성화 시 Grant 발급에 필수
      ]
      Resource = var.kms_key_eks_arn
    }]
  })
}
