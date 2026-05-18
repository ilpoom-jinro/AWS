variable "gcp_fixed_ip" {
  description = "GCP Tailscale node fixed external IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}

variable "oci_headscale_ip" {
  description = "OCI Headscale server IP (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}
