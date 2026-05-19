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
- optional Argo CD repository secret for CodeCommit

Run from the repository root:

```bash
ansible-galaxy collection install -r ansible/requirements.yml
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook ansible/playbooks/site.yml
```

To connect Argo CD to CodeCommit, set `gitops_repo_url` in
`ansible/group_vars/all.yml` or pass it at runtime:

```bash
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook ansible/playbooks/ops-argocd.yml \
  -e gitops_repo_url=https://git-codecommit.ap-northeast-2.amazonaws.com/v1/repos/gitops-platform
```

Argo CD CodeCommit access is intended to use EKS Pod Identity. Terraform creates
the IAM role and associates it with the `argocd/argocd-repo-server` service
account. The role needs `codecommit:GitPull` for the target repository ARN.
