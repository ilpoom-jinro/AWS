resource "aws_codecommit_repository" "gitops" {
  repository_name = var.gitops_codecommit_repository_name
  description     = "Internal GitOps source of truth for Argo CD"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name      = var.gitops_codecommit_repository_name
    Purpose   = "gitops-source-of-truth"
    ManagedBy = "terraform"
  }
}
