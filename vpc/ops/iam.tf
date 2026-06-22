# =============================================
# EKS 클러스터 Role KMS inline 정책
#
# key-eks 키 정책에서 클러스터 Role ARN을 직접 참조하면
# key 생성 시점에 Role이 아직 없어 MalformedPolicyDocumentException 발생.
# key 정책의 EnableRootAccess(kms:*)를 통한 IAM delegation으로 처리:
#   - 키 정책: root kms:* 허용 → IAM 위임 가능
#   - 여기: 클러스터 Role에 KMS 사용 권한 부여
# =============================================

# EBS CSI driver(Pod Identity role)가 key-eks로 암호화된 동적 PVC 볼륨을
# 생성/attach할 때 필요한 KMS 권한.
# AmazonEBSCSIDriverPolicy(AWS managed)에는 KMS 권한이 없어서, 암호화 볼륨이
# CreateVolume 직후 비동기 KMS 검증에 실패하고 사라졌음(InvalidVolume.NotFound).
# etcd 암호화와 동일한 IAM delegation 패턴 — key policy를 건드리지 않아
# prevent_destroy 키, EKS encryption_config(immutable)에 영향 없음.
resource "aws_iam_role_policy" "ebs_csi_kms" {
  name = "${var.eks_cluster_name}-ebs-csi-kms-policy"
  role = aws_iam_role.ebs_csi.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 데이터키 생성/복호화 — 볼륨 암호화·복호화에 필요.
        # Resource를 key-eks ARN으로 한정(least-privilege).
        Sid    = "AllowEBSCSIDriver"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = var.kms_key_eks_arn
      },
      {
        # 볼륨용 grant 생성 — EBS가 attach 시 복호화하려면 필요.
        # GrantIsForAWSResource=true로 제한해 임의 grant 생성 차단.
        Sid      = "AllowEBSCSIDriverCreateGrant"
        Effect   = "Allow"
        Action   = "kms:CreateGrant"
        Resource = var.kms_key_eks_arn
        Condition = {
          Bool = { "kms:GrantIsForAWSResource" = "true" }
        }
      }
    ]
  })
}

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
