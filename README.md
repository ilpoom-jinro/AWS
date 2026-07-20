# 금융권 멀티클라우드 통합 관제 플랫폼 - AWS

금융 환경을 가정한 **하이브리드·멀티클라우드 통합 관제 플랫폼**의 AWS 구현 저장소입니다. Terraform으로 AWS 기반 인프라를 구성하고, GitHub Actions·ECR·내부 Git·Argo CD를 연결한 GitOps 방식으로 서비스와 MAS(Multi-Agent System) 워크로드를 배포합니다.

> 이 저장소는 실제 금융사 고객 데이터나 프로덕션 트래픽을 처리하지 않는 프로젝트 환경입니다. 비밀값은 Git에 저장하지 않으며, AWS Secrets Manager와 GitHub Secrets를 통해서만 주입합니다.

## 프로젝트 개요

플랫폼은 운영 이벤트를 관측하고, 시나리오별 에이전트가 분석한 결과를 사람의 승인(HITL) 후 실행하는 흐름을 구현합니다.

| 영역 | 구현 범위 | 주요 구성 |
| --- | --- | --- |
| FinOps | 비용·용량·트래픽 분석 및 최적화 제안 | FinOps 에이전트, Temporal, Athena/CUR 연동 경로 |
| AIOps | 장애 탐지, 재시작·스케일 아웃·롤백 리허설 | AIOps 오케스트레이터, Slack HITL, Kubernetes API |
| SecOps | 보안 이벤트 분석 및 격리 정책 적용 | SecOps 오케스트레이터, Bedrock KB, Cilium 정책 |
| 관측성 | 로그·메트릭·트레이스의 중앙 수집과 대시보드 | Alloy, Loki, Thanos, Tempo, Grafana, Alertmanager |
| 플랫폼 보안·복구 | 비밀 관리, 네트워크 정책, 이미지 서명, 백업 | External Secrets, Cilium, Cosign, Velero, KMS |

AWS에는 목적이 분리된 두 EKS 클러스터를 운영합니다.

| 클러스터 | 역할 |
| --- | --- |
| `financial-service-eks` | 공개 프런트엔드, 백엔드 API, 서비스 측 관측 에이전트 |
| `financial-ops-eks` | MAS, Grafana·Loki·Thanos·Tempo·Alertmanager, 내부 GitOps 및 운영 도구 |

GCP DR 환경 및 OCI Headscale 연동에 필요한 AWS 측 네트워크·Route 53·자격 증명 구성도 이 저장소에서 관리합니다.

## 아키텍처

```mermaid
flowchart TB
  Dev[개발자 / GitHub] --> GA[GitHub Actions\nOIDC 인증]
  GA --> ECR[Amazon ECR\n이미지 빌드·서명]
  GA --> CB[AWS CodeBuild\n인프라·매니페스트 작업]
  CB --> Git[Internal Git]
  Git --> Argo[Argo CD]

  subgraph AWS[AWS · ap-northeast-2]
    direction TB
    subgraph Service[financial-service-eks]
      FE[React/Vite 프런트엔드]
      API[FastAPI 백엔드]
      SAlloy[Alloy]
      FE --> API
      FE --> SAlloy
      API --> SAlloy
    end

    subgraph Ops[financial-ops-eks]
      Argo --> MAS[FinOps · AIOps · SecOps MAS]
      MAS --> Temporal[Temporal]
      MAS --> Bedrock[Amazon Bedrock / KB]
      MAS --> HITL[Slack HITL\nSQS + Lambda 브로커]
      MAS --> RDS[(Amazon RDS\nPostgreSQL)]
      OAlloy[Alloy] --> Loki[Loki]
      OAlloy --> Thanos[Thanos]
      OAlloy --> Tempo[Tempo]
      Loki --> Grafana[Grafana]
      Thanos --> Grafana
      Tempo --> Grafana
      Alert[Alertmanager] --> MAS
      Cilium[Cilium NetworkPolicy] --- MAS
    end

    SM[AWS Secrets Manager] --> ESO[External Secrets]
    ESO --> MAS
    SAlloy --> OAlloy
  end

  AWS <-->|VPN / DR 연동| Hybrid[GCP DR · OCI Headscale]
```

1. GitHub Actions가 OIDC로 AWS 역할을 Assume하고, 이미지와 인프라 변경을 처리합니다.
2. 이미지에는 Cosign 서명을 적용하고, GitOps 매니페스트는 내부 Git을 통해 Argo CD가 동기화합니다.
3. 서비스 클러스터의 Alloy는 Ops 클러스터의 내부 NLB를 통해 로그·메트릭·트레이스를 전송합니다.
4. MAS는 Temporal로 작업을 조율하고, 필요한 경우 Bedrock 및 RDS를 사용합니다. 자동 조치는 Slack HITL 승인 경로를 거치도록 설계되어 있습니다.

## 기술 스택 및 버전

아래 버전은 저장소의 Terraform 설정, CI 워크플로우, Dockerfile, Helm Chart와 이미지 미러 설정을 기준으로 합니다.

| 구분 | 기술 | 버전 |
| --- | --- | --- |
| IaC | Terraform CLI | `1.11.0` (최소 요구 `>= 1.11.0`) |
| IaC | HashiCorp AWS Provider | `~> 5.0` |
| 컨테이너 오케스트레이션 | Amazon EKS / Kubernetes | `1.35` |
| GitOps | Argo CD, Kustomize, Helm | 내부 Git 기반 배포 |
| 서비스 런타임 | Python | `3.12.13-slim` |
| 백엔드 | FastAPI / Uvicorn | `0.115.6` / `0.34.0` |
| 워크플로우 | Temporal Server / Python SDK | `1.31.0` / `1.27.2` |
| 데이터베이스 | Amazon RDS PostgreSQL | 관리형 PostgreSQL |
| AI | Amazon Bedrock, Bedrock Knowledge Bases | 리전 `ap-northeast-2` |
| 프런트엔드 | Node.js / React / Vite | `22.23.1` / `19` / `6.4.3` |
| 관측성 | Grafana / Loki / Thanos / Tempo / Alloy | `13.1.0` / `3.7.3` / `0.41.0` / `3.0.0` / `1.17.1` |
| 네트워크·보안 | Cilium, AWS Load Balancer Controller | `1.16.5` / `3.3.0` |
| 비밀·백업 | External Secrets / Velero | `0.10.7` / `1.15.0` |

## 저장소 구성

```text
.
├── vpc/                 # Service·Ops·Teleport·Headscale VPC와 EKS 모듈
├── iam/, kms/, security/ # IAM, KMS, CloudTrail·SIEM·탐지 구성
├── gitops/platform/     # Argo CD Application, Helm 값, Kustomize 매니페스트
├── mas/                 # FinOps·AIOps·SecOps·플랫폼 에이전트 및 공용 계약
├── demo-app/            # React 프런트엔드와 FastAPI 백엔드 예제
├── monitoring/          # 관측 컴포넌트 이미지 및 인덱서
├── ansible/             # 클러스터 부트스트랩·운영 플레이북
└── .github/workflows/   # Terraform, 이미지, MAS, 앱 배포 자동화
```

## 실행 및 배포 방법

### 사전 요구 사항

- AWS 권한: Terraform 상태 버킷과 대상 계정 리소스에 접근 가능한 IAM 역할 또는 로컬 AWS 프로파일
- 도구: Terraform `1.11.0`, AWS CLI v2, `kubectl`, Docker, Helm, Git
- 선택 도구: Python `3.12`, Node.js `22` (로컬 애플리케이션 개발용)
- 네트워크: Ops EKS API와 내부 서비스는 사설 접근을 전제로 하므로, 해당 VPC에 접근 가능한 환경에서 운영 명령을 실행해야 합니다.

### 1. 인프라 계획 및 적용

공유 상태를 보호하기 위해 팀 환경에서는 로컬 `apply`보다 GitHub Actions의 **Terraform Operations** 워크플로우를 사용합니다. `plan`으로 변경 사항을 먼저 검토한 뒤 `apply` 또는 필요한 범위의 작업을 실행합니다.

로컬에서 검증만 하려면 다음을 실행합니다.

```bash
terraform init -reconfigure
terraform fmt -check -recursive
terraform validate
terraform plan -input=false -lock-timeout=5m
```

`apply`는 실제 AWS 리소스를 생성·변경하므로, 승인된 변경에 한해 실행합니다.

```bash
terraform apply -input=false -lock-timeout=5m
```

### 2. 클러스터 접속 및 GitOps 동기화

```bash
aws eks update-kubeconfig --region ap-northeast-2 --name financial-ops-eks
kubectl get pods -A
kubectl -n argocd get applications
```

Argo CD는 `gitops/platform/`의 Application·Helm·Kustomize 구성을 읽습니다. 매니페스트를 직접 ECR에 업로드하지 않으며, 컨테이너 이미지만 ECR에 저장합니다.

### 3. 애플리케이션 및 MAS 배포

- `App Deploy`: 데모 애플리케이션 이미지를 ECR에 빌드·서명하고, CodeBuild가 내부 GitOps 매니페스트의 이미지 태그를 갱신합니다.
- `MAS Agent Deploy`: `mas/pods/<scenario>/<agent>/agent.yml`을 기준으로 MAS 이미지를 빌드·서명하고 배포 매니페스트를 갱신합니다.
- `ECR Images` 및 `Monitoring Images`: 외부 이미지를 내부 ECR로 미러링합니다.

각 워크플로우를 실행한 뒤 Argo CD의 동기화 상태와 워크로드 상태를 확인합니다.

```bash
kubectl -n argocd get applications
kubectl -n aiops-mas get deploy,pods
kubectl -n secops-mas get deploy,pods
kubectl -n finops-mas get deploy,pods
```

### 4. 로컬 MAS 감사 DB 시연

로컬 시연은 RDS 대신 PostgreSQL 컨테이너만 실행합니다.

```bash
cd mas/deploy/local
docker compose up -d
```

애플리케이션에는 다음 형식의 연결 문자열을 주입합니다.

```bash
export DATABASE_URL='postgresql+asyncpg://mas:mas@localhost:5432/mas'
```

종료는 `docker compose down`을 사용합니다. `-v` 옵션은 로컬 볼륨 데이터를 제거하므로 필요할 때만 사용합니다.

## 환경 변수 및 비밀값 설정

### GitHub Actions Secrets 및 Variables

다음 값은 GitHub 저장소의 **Settings → Secrets and variables → Actions**에 설정합니다. AWS 자격 증명은 장기 액세스 키가 아닌 OIDC 역할 연동을 사용합니다.

| 이름 | 구분 | 용도 |
| --- | --- | --- |
| `AWS_ROLE_ARN_DEV` | Secret | 개발 환경 GitHub Actions OIDC AssumeRole ARN |
| `AWS_ROLE_ARN` | Secret | 일부 앱·MAS 이미지 워크플로우에서 사용하는 OIDC 역할 ARN |
| `AWS_REGION` | Secret | 기본 리전. 미설정 시 `ap-northeast-2` |
| `GCP_FIXED_IP` | Secret | GCP Tailscale 노드의 고정 공인 IP/CIDR |
| `OCI_HEADSCALE_IP` | Secret | OCI Headscale 서버 IP/CIDR |
| `OCI_HEADSCALE_IP_PLAIN` | Secret | OCI Headscale 서버의 일반 IP |
| `TAILSCALE_AUTH_KEY` | Secret | Headscale 등록용 Tailscale 인증 키 |
| `GCP_SERVICE_IP` | Variable | DR 서비스 LB의 고정 IP |
| `GCP_CLOUDSQL_PRIVATE_IP` | Variable | DR Cloud SQL 사설 IP |

### Terraform 입력 변수

로컬 실행 시 민감한 값은 셸 환경 변수로 전달하고, `terraform.tfvars`에 실제 키를 기록하거나 커밋하지 않습니다.

```bash
export TF_VAR_gcp_fixed_ip='203.0.113.10/32'
export TF_VAR_oci_headscale_ip='198.51.100.20/32'
export TF_VAR_oci_headscale_ip_plain='198.51.100.20'
export TF_VAR_tailscale_auth_key='발급받은-인증-키'
export TF_VAR_gcp_service_ip='203.0.113.30'
export TF_VAR_gcp_cloudsql_private_ip='10.0.0.10'
```

예시 IP와 인증 키는 자리 표시자이며 실제 값으로 바꿔야 합니다. 개발 비용 설정은 기본적으로 `single_az_mode=true`, `rds_backup_retention=0`입니다. 운영 전환 전에는 가용성과 백업 보존 정책을 검토하여 별도 값으로 명시해야 합니다.

### AWS Secrets Manager와 Kubernetes 주입

Terraform은 RDS 및 Temporal용 시크릿 컨테이너를 만들고, Kubernetes에서는 External Secrets가 필요한 키를 Secret으로 동기화합니다.

| AWS Secrets Manager 이름 | 관리 방식 | 사용처 |
| --- | --- | --- |
| `financial-service-rds-password` | Terraform 생성·회전 | 서비스 RDS 연결 |
| `financial-ops-rds-password` | Terraform 생성·회전 | Ops RDS 및 감사 로그 |
| `temporal/rds-credentials` | Terraform 생성 | Temporal 및 Temporal Visibility DB |
| `financial-slack-hitl-tokens` | Terraform은 컨테이너만 생성, 값은 별도 주입 | Slack 브로커 Lambda |

Slack 브로커 시크릿에는 최소 `slack_bot_token`, `signing_secret` 키가 필요합니다. 평문 토큰을 Kubernetes 매니페스트, `.env`, Terraform 상태, GitHub Actions 로그에 출력하지 마십시오.

## 관련 문서

- [GitOps 플랫폼 안내](gitops/platform/README.md)
- [MAS 구조 및 에이전트 배포 규약](mas/README.md)
- [모니터링 이미지 관리](monitoring/README.md)
- [보안 정책](SECURITY.md)
- [취약점 관리 정책](VULNERABILITY-MANAGEMENT.md)

---

문서 기준일: 2026-07-20 · 기준 커밋: `dd505fd`
