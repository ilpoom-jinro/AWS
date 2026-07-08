# vpc/globalservice/eks-access-entry-aiops.tf
# ops의 aiops-orchestrator(Pod Identity role)가 service 클러스터를 조회/조작할 수 있도록
# access entry를 등록한다. 이것이 있어야 boto3 get-token으로 생성한 bearer 토큰이
# service 클러스터에서 인증된다. 실제 인가는 EKS access policy와 K8s RBAC가 담당한다.
#
# role ARN은 이름이 고정(financial-ops-mas-orchestrator-role)이라 조합으로 참조하여
# vpc/ops 모듈과의 순환 의존을 피한다.

locals {
  ops_mas_orchestrator_role_arn = "arn:aws:iam::${var.account_id}:role/financial-ops-mas-orchestrator-role"
}

# 1) access entry: role을 클러스터에 등록 (인증 허용)
resource "aws_eks_access_entry" "aiops_orchestrator" {
  cluster_name  = aws_eks_cluster.service.name
  principal_arn = local.ops_mas_orchestrator_role_arn
  type          = "STANDARD"

  tags = {
    ManagedBy = "terraform"
    Purpose   = "aiops-cross-cluster-remediation"
  }
}

# 2) access policy: 탐지/분석용 읽기 권한.
resource "aws_eks_access_policy_association" "aiops_orchestrator_view" {
  cluster_name  = aws_eks_cluster.service.name
  principal_arn = local.ops_mas_orchestrator_role_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.aiops_orchestrator]
}

# 3) access policy: HITL 승인 후 execute 단계에서 rollout restart, HPA patch 등
#    워크로드 변경을 수행하기 위한 권한.
resource "aws_eks_access_policy_association" "aiops_orchestrator_edit" {
  cluster_name  = aws_eks_cluster.service.name
  principal_arn = local.ops_mas_orchestrator_role_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.aiops_orchestrator]
}
