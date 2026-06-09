# AIOps Bedrock Agent

VPC2(내부 운영망) 상주 멀티클라우드 장애 탐지·복구 에이전트

## 구성요소

| 파일 | 역할 |
|------|------|
| `src/aiops/graph.py` | LangGraph 상태 머신 조립 |
| `src/aiops/state.py` | AgentState TypedDict |
| `src/aiops/main.py` | FastAPI 진입점 + 에이전트 루프 |
| `src/aiops/nodes/monitor.py` | VPC1+VPC2 EKS 파드/메트릭 수집 |
| `src/aiops/nodes/detector.py` | CrashLoop/OOM/ImagePull/Pending/Evicted 감지 |
| `src/aiops/nodes/analyzer.py` | Bedrock Claude RCA 분석 |
| `src/aiops/nodes/planner.py` | 복구 전략 우선순위 결정 |
| `src/aiops/nodes/approver.py` | Slack HITL 승인 대기 |
| `src/aiops/nodes/executor.py` | kubectl/helm 복구 실행 |
| `src/aiops/nodes/verifier.py` | 5분 재모니터링 |
| `src/aiops/nodes/rollback.py` | 자동 롤백 |
| `terraform/aiops-agent.tf` | IRSA Role + Bedrock Endpoint + Secrets |
| `k8s/` | EKS 배포 매니페스트 |
| `Dockerfile` | 컨테이너 빌드 |

## 배포 순서

```bash
# 1. Terraform — Bedrock Endpoint + IRSA Role 생성
terraform apply -target=aws_vpc_endpoint.bedrock_runtime \
                -target=aws_iam_role.aiops_agent \
                -target=aws_secretsmanager_secret_version.slack_bot_token

# 2. ECR 이미지 빌드 & 푸시
docker build -t 218549830271.dkr.ecr.ap-northeast-2.amazonaws.com/financial/aiops-agent:latest .
docker push 218549830271.dkr.ecr.ap-northeast-2.amazonaws.com/financial/aiops-agent:latest

# 3. EKS 배포
kubectl apply -k k8s/

# 4. 확인
kubectl -n aiops get pods
kubectl -n aiops logs -f deploy/aiops-agent
```

## 시연 (CrashLoop)

```bash
# 장애 유발
kubectl set env deployment/backend -n service-apps CRASH_ON_START=true

# 30초 후 에이전트가 감지 → Slack 승인 요청 발송
# Slack에서 ✅ 승인 클릭 → 복구 실행 → 5분 후 재검증
# 환경변수 미제거 시 재이상 감지 → 자동 롤백
```
