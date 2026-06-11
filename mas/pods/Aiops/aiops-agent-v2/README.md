# AIOps Bedrock Agent (v0.2)

VPC2(내부 운영망) 상주 멀티클라우드 장애 탐지·복구 에이전트

## v0.2 주요 수정사항 (구동 불가 버그 수정)

| # | 심각도 | 파일 | 문제 → 수정 |
|---|--------|------|------------|
| 1 | Critical | pyproject.toml | 존재하지 않는 build-backend → `setuptools.build_meta` |
| 2 | Critical | Dockerfile | builder에 src 미복사, curl purge 후 HEALTHCHECK 사용, aws CLI 부재 → 전면 재작성 + entrypoint.sh |
| 3 | Critical | graph.py | 내부 무한루프 → recursion limit 크래시 → END 종료 구조 |
| 4 | Critical | main.py | async 노드를 sync invoke() → `ainvoke()` |
| 5 | Critical | tools/slack.py | 토큰 로드 전 import 시점 클라이언트 생성 → lazy singleton |
| 6 | Critical | tools/k8s_client.py | in-cluster config가 context 무시 → kubeconfig + new_client_from_config |
| 7 | Critical | terraform | 존재하지 않는 module output 참조 → EKS Pod Identity 전환 |
| 8 | Major | nodes/detector.py | SDK datetime 타입 미처리, vpc1 로그를 ops에서 수집 → 수정 |
| 9 | Major | nodes/analyzer.py | 동기 boto3가 이벤트 루프 블로킹 → run_in_executor |
| 10 | Major | k8s/deployment.yaml | KUBECONFIG/클러스터명 env 부재, nodeSelector Pending 위험 → 수정 |

## 배포 순서

```bash
# 1. Terraform — Pod Identity + Bedrock Endpoint + Secrets
terraform apply \
  -target=aws_iam_role.aiops_agent \
  -target=aws_iam_role_policy.aiops_agent \
  -target=aws_eks_pod_identity_association.aiops \
  -target=aws_vpc_endpoint.bedrock_runtime \
  -target=aws_eks_access_entry.aiops_ops \
  -target=aws_eks_access_policy_association.aiops_ops \
  -target=aws_eks_access_entry.aiops_svc \
  -target=aws_eks_access_policy_association.aiops_svc \
  -target=aws_secretsmanager_secret_version.slack_bot_token \
  -target=aws_ecr_repository.aiops_agent

# 2. 클러스터 이름 확인 → k8s/configmap.yaml의 REPLACE_* 교체
terraform output aiops_ops_cluster_name
terraform output aiops_service_cluster_name

# 3. ECR 이미지 빌드 & 푸시
# ECR_REGISTRY는 terraform output aiops_agent_ecr_url에서 확인 (계정 이관 대응으로 하드코딩 제거)
ECR_REGISTRY=$(terraform output -raw aiops_agent_ecr_url | cut -d/ -f1)
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REGISTRY
docker build -t $ECR_REGISTRY/financial/aiops-agent:latest .
docker push $ECR_REGISTRY/financial/aiops-agent:latest

# 4. EKS 배포
kubectl apply -k k8s/

# 5. 확인
kubectl -n aiops logs -f deploy/aiops-agent
# 기대 로그: "[entrypoint] Ops EKS 컨텍스트 등록" → "AIOps Agent 시작"
```

## 시연 (CrashLoop → 자동 롤백)

```bash
kubectl set env deployment/backend -n service-apps CRASH_ON_START=true
# 30초 내 감지 → Slack 승인 요청 → ✅ 클릭 → restart 실행
# → 5분 후 재검증 → (env 미제거 시) 재이상 감지 → 자동 rollout undo
```

## 사전 조건 체크리스트

- [ ] Ops EKS에 `eks-pod-identity-agent` 애드온 설치됨 (기존 EBS CSI용으로 설치되어 있음)
- [ ] VPC2에 Secrets Manager VPC Endpoint 존재 (기존 endpoints.tf에 있음)
- [ ] configmap.yaml의 `REPLACE_WITH_*` 클러스터 이름 교체
- [ ] Slack App: Bot Token Scopes `chat:write`, `chat:write.public`
- [ ] Slack Interactivity Request URL 등록 (ingress.yaml 또는 ngrok)

## v0.3 — 계정 이관 + 신규 인프라(AWS-feature-Aiops) 대응

팀 인프라가 새 AWS 계정으로 이관되고 모니터링 스택이 교체됨에 따라 다음을 반영:

| 항목 | 변경 |
|------|------|
| 메트릭 엔드포인트 | `prometheus-server.monitoring:80` → **`observability-thanos-query.observability:9090`** (Thanos Query, Prometheus 호환 API) |
| PromQL 쿼리 | kube-state-metrics 부재로 `kube_pod_*` 시리즈 제거, cadvisor 기반(`container_*`)으로 정리 — 파드 상태 탐지는 K8s API 직접 조회라 영향 없음 |
| 멀티클러스터 메트릭 | Service EKS 메트릭도 Alloy→NLB→Thanos Receive로 모이므로 Thanos Query 한 곳에서 양쪽 조회 가능 (`cluster` 레이블로 구분) |
| 이미지 레지스트리 | 계정 ID 하드코딩 제거 → `REPLACE_WITH_ECR_REGISTRY` 플레이스홀더 (terraform output으로 교체) |
| 노드 배치 | 모니터링 노드 레이블 `role=monitoring` 확정. 단 single_az_mode에서는 nodeSelector 해제 비권장 (toleration만 유지) |
| 배치 경로 | 팀 레포 기준 `mas/pods/Aiops/aiops-agent-v1/` 에 위치, Terraform은 루트 `aiops-agent.tf` |
