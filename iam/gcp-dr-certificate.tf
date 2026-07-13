# GCP_sub main workflows can change only the ACME DNS-01 TXT records required
# to issue the GKE DR Gateway certificate.
resource "aws_iam_role" "gcp_dr_certificate" {
  name        = "ilpumjinro-gcp-dr-certificate-role"
  description = "Route 53 DNS-01 role for the GCP DR TLS workflow"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:ilpoom-jinro/GCP_sub:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "gcp_dr_certificate" {
  name = "gcp-dr-certificate-route53-dns01"
  role = aws_iam_role.gcp_dr_certificate.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ManageOnlyAcmeChallengeTxtRecords"
        Effect   = "Allow"
        Action   = ["route53:ChangeResourceRecordSets"]
        Resource = aws_route53_zone.main.arn
        Condition = {
          "ForAllValues:StringEquals" = {
            "route53:ChangeResourceRecordSetsNormalizedRecordNames" = [
              "_acme-challenge.ilpumjinro.store",
              "_acme-challenge.gcp.ilpumjinro.store"
            ]
            "route53:ChangeResourceRecordSetsRecordTypes" = ["TXT"]
            "route53:ChangeResourceRecordSetsActions"     = ["CREATE", "UPSERT", "DELETE"]
          }
        }
      },
      {
        Sid      = "DiscoverHostedZones"
        Effect   = "Allow"
        Action   = ["route53:ListHostedZones"]
        Resource = "*"
      },
      {
        Sid      = "ReadDnsChanges"
        Effect   = "Allow"
        Action   = ["route53:GetChange"]
        Resource = "*"
      }
    ]
  })
}

output "gcp_dr_certificate_role_arn" {
  description = "GCP_sub Secret AWS_DR_CERTIFICATE_ROLE_ARN value for DNS-01 TLS issuance"
  value       = aws_iam_role.gcp_dr_certificate.arn
}
