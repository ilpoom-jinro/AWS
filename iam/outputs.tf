# onfrem 액세스 키 — terraform apply 후 민수님께 전달
output "onfrem_access_key_id" {
  value = aws_iam_access_key.onfrem.id
}

output "onfrem_secret_access_key" {
  value     = aws_iam_access_key.onfrem.secret
  sensitive = true
}
