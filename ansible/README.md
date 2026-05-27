# Ansible EKS Configuration

This directory handles Kubernetes-level configuration after Terraform creates
the AWS infrastructure.

Terraform owns:

- VPCs, subnets, routing, security groups
- EKS clusters and managed node groups
- IAM roles and policies

Ansible owns:

- kubeconfig context setup
- Argo CD installation on the Internal Ops EKS cluster
- basic Service EKS namespace bootstrap
- internal Git repository bootstrap for Argo CD

Run from the repository root:

```bash
ansible-galaxy collection install -r ansible/requirements.yml
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook ansible/playbooks/site.yml
```

Argo CD is configured to use the internal Git service by default. The repository
URL is defined as `gitops_repo_url` in `ansible/group_vars/all.yml`.
