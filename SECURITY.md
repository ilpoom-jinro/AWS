# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please use [GitHub Private Vulnerability Reporting](https://github.com/ilpoom-jinro/AWS/security/advisories/new) to report vulnerabilities privately.

### What to include

- Description of the vulnerability and its potential impact
- Steps to reproduce or proof-of-concept
- Affected files or components
- Suggested fix (optional)

### Response process

| Stage | Timeframe |
|-------|-----------|
| Acknowledgement | Within 3 business days |
| Initial assessment | Within 7 business days |
| Patch and disclosure | Coordinated with reporter |

## Scope

This repository contains AWS infrastructure-as-code (Terraform), GitOps manifests, and CI/CD workflows. The following are in scope:

- Hardcoded credentials or secrets in source code
- IAM policy misconfigurations that could allow privilege escalation
- GitHub Actions workflow vulnerabilities (e.g., script injection, excessive permissions)
- Insecure Terraform configurations

## Out of Scope

- Issues in upstream dependencies (Terraform providers, Helm charts, container images) — report those to the respective projects
- Issues in AWS managed services themselves — report to [AWS Security](https://aws.amazon.com/security/vulnerability-reporting/)

## Supported Versions

Only the latest commit on the `main` branch is actively maintained.
