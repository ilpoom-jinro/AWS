# 나의 작업 체크리스트: 관제 GitOps 배포

## 현재 구성

| VPC        | EKS                     | 배포 대상                                                                |
| ---------- | ----------------------- | ------------------------------------------------------------------------ |
| 서비스 VPC | `financial-service-eks` | Frontend, Backend, Alloy                                                 |
| Ops VPC    | `financial-ops-eks`     | Grafana, Loki, Thanos, Alertmanager, Alloy, AWS Load Balancer Controller |

Frontend와 Backend는 같은 서비스 EKS에서 실행됩니다. Frontend는
Kubernetes 내부 DNS `http://backend:8000`으로 Backend를 호출합니다.

## 이미 완료한 작업

| 상태 | 작업                                                | 확인 위치                                       |
| ---- | --------------------------------------------------- | ----------------------------------------------- |
| [x]  | 서비스 VPC Alloy 로그 및 메트릭 수집 규칙 작성      | `helmChart/alloy-service/values.yaml`           |
| [x]  | Ops VPC Alloy 로그 및 메트릭 수집 규칙 작성         | `helmChart/alloy-ops/values.yaml`               |
| [x]  | Loki, Thanos, Grafana, Alertmanager Helm Chart 준비 | `helmChart/charts`                              |
| [x]  | Loki와 Alloy의 불필요한 외부 보조 이미지 최소화     | `helmChart/loki/values.yaml`, Alloy values      |
| [x]  | AWS Load Balancer Controller 공식 Helm Chart 준비   | `helmChart/charts/aws-load-balancer-controller` |
| [x]  | Controller values와 Argo CD Application 골격 작성   | `helmChart/aws-load-balancer-controller`        |

## 팀원 값을 받은 뒤 할 작업

| 상태 | 순서 | 나의 작업                                             | 입력받을 값                   |
| ---- | ---: | ----------------------------------------------------- | ----------------------------- |
| [ ]  |    1 | Controller values의 Ops VPC ID 교체                   | Ops VPC ID                    |
| [ ]  |    2 | Loki values에 Loki NLB SG ID 입력                     | Loki NLB SG ID                |
| [ ]  |    3 | Thanos values에 Thanos Receive NLB SG ID 입력         | Thanos Receive NLB SG ID      |
| [ ]  |    4 | GitOps 파일을 내부 Git `gitadmin/platform.git`에 반영 | 내부 Git 접근                 |
| [ ]  |    5 | Argo CD에서 Controller Application 동기화             | Controller IAM 연동 완료 여부 |
| [ ]  |    6 | Argo CD에서 Loki와 Thanos Application 동기화          | Controller Pod 실행 확인      |
| [ ]  |    7 | 생성된 Loki와 Thanos internal NLB DNS 확인            | AWS 콘솔 또는 담당 팀원       |
| [ ]  |    8 | 서비스 Alloy values의 NLB DNS 자리표시자 교체         | internal NLB DNS 두 개        |
| [ ]  |    9 | 서비스 Alloy와 Ops Alloy Application 동기화           | NLB DNS 반영 완료             |
| [ ]  |   10 | Grafana에서 Loki 로그와 Thanos 메트릭 유입 확인       | 배포 완료                     |

## 아직 작성해야 하는 Argo CD Application

아래 Kubernetes YAML은 존재하지만 Argo CD Application은 아직 없습니다.

| 상태 | 대상               | 현재 YAML 위치                                                    | 필요한 작업                        |
| ---- | ------------------ | ----------------------------------------------------------------- | ---------------------------------- |
| [ ]  | Frontend와 Backend | `financial-service-eks/frontend`, `financial-service-eks/backend` | 서비스 EKS 배포용 Application 작성 |

## NLB 생성 후 교체할 값

`helmChart/alloy-service/values.yaml`의 자리표시자를 실제 DNS로 바꿉니다.

| 상태 | 자리표시자                                  | 교체할 값                       |
| ---- | ------------------------------------------- | ------------------------------- |
| [ ]  | `loki-internal-nlb.example.local`           | Loki internal NLB DNS           |
| [ ]  | `thanos-receive-internal-nlb.example.local` | Thanos Receive internal NLB DNS |
| [ ]  | `tempo-internal-nlb.example.local`          | Tempo internal NLB DNS          |

## RDS와 IAM 후속 작업

| 상태 | 작업                                       | 비고                                                |
| ---- | ------------------------------------------ | --------------------------------------------------- |
| [ ]  | 백엔드 YAML에 서비스 VPC RDS Endpoint 입력 | RDS 생성 후 진행                                    |
| [ ]  | DB Secret 관리 방식 확정                   | 평문 비밀번호를 Git에 저장하지 않기                 |
| [ ]  | Grafana CloudWatch IAM Role 연동 확인      | Pod Identity Terraform 코드 작성 완료. 적용 후 확인 |
| [ ]  | Grafana CloudWatch 데이터소스 조회 테스트  | Role 연동 후 진행                                   |

## 나중에 진행할 작업

| 상태 | 작업                                         |
| ---- | -------------------------------------------- |
| [ ]  | Alertmanager 알림 채널 구성                  |
| [ ]  | 장기 보관용 S3 Object Storage 검토           |
| [ ]  | AI Agent용 S3 Vectors 인덱싱 파이프라인 구성 |
