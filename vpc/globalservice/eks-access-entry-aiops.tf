# vpc/globalservice/eks-access-entry-aiops.tf
# ops의 aiops-orchestrator(Pod Identity role)가 service 클러스터를 읽을 수 있도록
# access entry를 등록한다. 이것이 있어야 boto3 get-token으로 생성한 bearer 토큰이
# service 클러스터에서 인증된다. (K8s 리소스 권한은 별도 RBAC로 부여)
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
    Purpose   = "aiops-cross-cluster-read"
  }
}

# 2) access policy: 읽기 권한 부여 (ClusterAdmin 아님 — 최소권한).
#    파드/로그/이벤트 조회만 필요하므로 View 정책을 클러스터 범위로 연결.
#    (세밀한 제한이 필요하면 K8s RBAC ClusterRole로 추가 제약)
resource "aws_eks_access_policy_association" "aiops_orchestrator_view" {
  cluster_name  = aws_eks_cluster.service.name
  principal_arn = local.ops_mas_orchestrator_role_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.aiops_orchestrator]
}
