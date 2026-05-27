# ──────────────────────────────────────────────────────────────────────────────
# Teleport EC2 IAM Role — S3 세션 로그 접근 권한
# 버킷 자체는 bootstrap/teleport-s3.tf에서 관리
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role_policy" "teleport_s3" {
  name = "teleport-session-logs-s3"
  role = module.vpc3.teleport_ec2_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = [
        "arn:aws:s3:::ilpumjinro-teleport",
        "arn:aws:s3:::ilpumjinro-teleport/*"
      ]
    }]
  })
}
