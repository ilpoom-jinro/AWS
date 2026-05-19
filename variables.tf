variable "gcp_fixed_ip" {
  description = "GCP Tailscale node fixed external IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}

variable "oci_headscale_ip" {
  description = "OCI Headscale server IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}

variable "oci_headscale_ip_plain" {
  description = "OCI Headscale server IP (plain format, e.g. 1.2.3.4)"
  type        = string
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key for OCI Headscale registration"
  type        = string
  sensitive   = true
}

variable "gitops_codecommit_repository_name" {
  description = "CodeCommit repository name for the GitOps source of truth"
  type        = string
  default     = "gitops-platform"
}

variable "ansible_codebuild_image" {
  description = "CodeBuild image that includes ansible, kubectl, helm, awscli, and python kubernetes dependencies"
  type        = string
  default     = null
}

variable "ansible_codebuild_image_repository_name" {
  description = "ECR repository name for the Ansible CodeBuild runtime image"
  type        = string
  default     = "financial/ansible-codebuild"
}
