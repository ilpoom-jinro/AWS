# AIOps Agent (MAS Platform)

VPC2 Ops EKS 상주 AIOps 에이전트 — **MAS Platform Temporal Activities 구현체**

이전 독립 실행 구조(v0.3, LangGraph 자체 루프 + Slack WebHook)에서
팀 MAS 표준(contracts/shared/workflows)에 맞춰 전면 재구조화했습니다.

## 역할 (AIOpsActivities Protocol 구현)

| Activity | 입력 → 출력 | 구현 |
|----------|-----------|------|
| `detect_incident` | DetectIncidentInput → IncidentContext | nodes/detector.py |
| `analyze_root_cause` | IncidentContext → AnomalyReport | nodes/analyzer.py |
| `verify_recovery` | IncidentContext → RecoveryVerification | nodes/verifier.py |

> `execute_remediation` / `execute_rollback`는 **Platform Core가 구현** (협의 결정 2).
> Agent는 읽기 전용이며 실행 권한이 없습니다.

## MAS 정합 핵심

- **Bedrock**: `shared.bedrock.get_bedrock_client()` + `converse` API + `ClaudeModel.SONNET` (claude-sonnet-4-6). boto3 직접 호출 안 함.
- **데이터 모델**: `contracts.models`의 Pydantic 모델 사용 (IncidentContext, AnomalyReport, RemediationPlan 등).
- **anomaly_type 매핑** (팀 모델 6월 18일 반영 완료): CrashLoopBackOff→crashloop_backoff, OOMKilled→oom_killed, ImagePullBackOff/ErrImagePull→image_pull_backoff, PendingTimeout→pending_timeout, Evicted→evicted.
- **strategy 매핑**: investigate→manual.
- **로그 50줄 제한**: recent_logs는 Temporal payload 2MB 대응으로 최대 50줄.
- **메트릭 수집** (v1.2): detect_incident가 Thanos Query(읽기 전용)에서 cpu_usage_current / memory_usage_current / error_rate를 조회해 IncidentContext에 채움. ops/service 양쪽 클러스터는 cluster 레이블로 구분. 변경 없는 망 내부 통신이라 권한 추가·망분리 위반 없음.
- **메트릭 기반 RCA** (v1.2.1): analyze_root_cause 프롬프트가 메트릭을 퍼센트로 제시하고, anomaly_type과 메트릭의 상관관계를 교차 검증하도록 지침 제공 (예: OOM인데 메모리 높으면 scale_out 신뢰도↑, 5xx 높으면 rollback 우선). 메트릭 0.0은 "수집 실패"로 표기해 LLM이 로그에 더 의존하고 confidence를 낮추도록 유도.
- **흐름 제어**: LangGraph 자체 루프 → `AIOpsRemediationWorkflow` (Temporal). `get_activity_options`는 `ActivityName` Enum 인자 사용. 분석 단계는 Activity 내부 단일 Bedrock 호출.
- **Slack HITL**: approver.py 제거. Workflow가 `send_approval_request`(즉시 반환 ApprovalTicket) → signal(`approval_result`) + `wait_condition` 대기 → 4h 경과 시 `send_reminder` → 8h 경과 시 자동 거부.
- **감사 로그**: 워크플로우 단계별 `record_audit_log` (RDS PostgreSQL).
- **인증**: EKS Pod Identity (IRSA annotation 제거).

## 구조

```
mas/agents/aiops/
├── src/aiops/
│   ├── worker.py          # Temporal Worker 진입점 (main.py 대체)
│   ├── workflow.py        # AIOpsRemediationWorkflow (흐름 제어)
│   ├── activities.py      # @activity.defn 등록 (AIOpsActivities 구현)
│   ├── config.py          # AIOps 전용 설정
│   ├── k8s_collector.py   # 읽기 전용 K8s 수집 (실행 권한 없음)
│   ├── metrics_collector.py # 읽기 전용 Thanos 메트릭 수집
│   ├── mappers/           # anomaly_type / strategy 매핑
│   └── nodes/             # detect / analyze / verify 비즈니스 로직
├── k8s/                   # Worker Deployment (HTTP 포트 없음)
├── tests/
├── Dockerfile
├── entrypoint.sh          # kubeconfig 생성 후 python -m aiops.worker
└── pyproject.toml
```

## 의존성

`contracts`, `shared`, `workflows`는 mas 모노레포 루트 패키지입니다.
CI/로컬에서는 editable install 또는 `MAS_ROOT` 환경변수로 경로 지정.

## 배포

```bash
# 이미지
ECR=$(terraform output -raw aiops_agent_ecr_url | cut -d/ -f1)
docker build -t $ECR/financial/aiops-agent:latest .
docker push  $ECR/financial/aiops-agent:latest

# configmap의 REPLACE_WITH_* (클러스터명) + deployment의 ECR 교체 후
kubectl apply -f k8s/

# Secret: DATABASE_URL (감사 로그 RDS)
kubectl -n aiops create secret generic aiops-agent-secrets \
  --from-literal=database-url='postgresql+asyncpg://user:pass@rds-host:5432/mas_audit'
```

## 테스트

```bash
MAS_ROOT=/path/to/mas python tests/test_mas_integration.py
```
