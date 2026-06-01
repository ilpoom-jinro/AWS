# 팀원 요청사항: 관제용 internal NLB 사전 인프라

## 목적

서비스 VPC의 Alloy가 Ops VPC의 Loki와 Thanos Receive로 로그와 메트릭을
전송할 수 있도록 AWS 인프라를 준비해 주세요.

본 문서의 Terraform, ECR 저장소, IAM Role, Security Group 작업은 인프라
담당 팀원 작업입니다. 관제 Helm values와 Argo CD YAML은 제가 관리합니다.

## 요청 작업 체크리스트

| 상태 | 순서 | 요청 작업 | 적용 위치 예시 |
|---|---:|---|---|
| [ ] | 1 | Ops VPC에 ELB API Interface Endpoint 추가 | `AWS/vpc/ops/endpoints.tf` |
| [ ] | 2 | AWS Load Balancer Controller용 ECR 저장소 생성 | `AWS/ecr.tf` |
| [ ] | 3 | Controller 공식 이미지를 사설 ECR에 미러링 | `AWS/monitoring/images.tsv`, GitHub Actions |
| [ ] | 4 | Controller 전용 IAM Policy와 Role 생성 | `AWS/vpc/ops/load-balancer-controller.tf` |
| [ ] | 5 | Ops EKS Pod Identity Association 생성 | 같은 Terraform 파일 |
| [ ] | 6 | Loki internal NLB용 Security Group 생성 | `AWS/vpc/ops/security-groups.tf` |
| [ ] | 7 | Thanos Receive internal NLB용 Security Group 생성 | 같은 Terraform 파일 |
| [ ] | 8 | 필요한 Terraform output 추가 | `AWS/vpc/ops/outputs.tf`, `AWS/outputs.tf` |
| [ ] | 9 | `terraform plan` 검토 후 `terraform apply` | AWS 저장소 |

## 1. ELB API Endpoint

Ops VPC는 인터넷이 차단되어 있습니다. Ops EKS에 설치될 Controller가
AWS ELB API에 내부망으로 요청할 수 있도록 아래 Interface Endpoint가
필요합니다.

```text
com.amazonaws.ap-northeast-2.elasticloadbalancing
```

기존 Ops VPC Endpoint와 같은 형태로 추가해 주세요.

```hcl
resource "aws_vpc_endpoint" "elasticloadbalancing" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.elasticloadbalancing"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
}
```

## 2. Controller ECR 저장소와 이미지

아래 ECR 저장소를 Terraform으로 생성해 주세요.

```text
financial/system/aws-load-balancer-controller
```

아래 공식 이미지를 사설 ECR로 미러링해 주세요.

```text
원본: public.ecr.aws/eks/aws-load-balancer-controller:v3.3.0
대상: 218549830271.dkr.ecr.ap-northeast-2.amazonaws.com/financial/system/aws-load-balancer-controller:v3.3.0
```

## 3. Controller IAM Role

Ops EKS의 AWS Load Balancer Controller Pod가 internal NLB, Listener,
Target Group과 관련 Security Group 규칙을 관리할 수 있도록 공식 Controller
IAM Policy 기반의 Role을 생성해 주세요.

이 저장소는 EKS Pod Identity를 사용하므로 아래 값으로 Association도 생성해
주세요.

| 항목 | 값 |
|---|---|
| EKS Cluster | `financial-ops-eks` |
| Namespace | `kube-system` |
| ServiceAccount | `aws-load-balancer-controller` |

## 4. NLB Security Group

두 개의 NLB 전용 Security Group을 분리해서 생성해 주세요.

| Security Group | 허용 출발지 | Inbound 포트 | 용도 |
|---|---|---:|---|
| Loki NLB SG | `10.10.11.0/24`, `10.10.12.0/24` | `3100/TCP` | 서비스 VPC Alloy 로그 전송 |
| Thanos Receive NLB SG | `10.10.11.0/24`, `10.10.12.0/24` | `19291/TCP` | 서비스 VPC Alloy 메트릭 전송 |

서비스 VPC 전체 CIDR보다 서비스 EKS 프라이빗 서브넷 CIDR만 허용해 주세요.

## 작업 완료 후 전달해 주세요

| 상태 | 전달받을 값 | 예시 |
|---|---|---|
| [ ] | Ops VPC ID | `vpc-xxxxxxxx` |
| [ ] | ELB API Endpoint 생성 완료 여부 | `Available` |
| [ ] | Controller ECR 이미지 URI | `218549830271.dkr.ecr.ap-northeast-2.amazonaws.com/financial/system/aws-load-balancer-controller:v3.3.0` |
| [ ] | Controller Pod Identity Association 완료 여부 | `완료` |
| [ ] | Loki NLB SG ID | `sg-xxxxxxxx` |
| [ ] | Thanos Receive NLB SG ID | `sg-yyyyyyyy` |

## 이후 별도로 필요한 값

아래 값은 internal NLB 작업과 별개입니다. 해당 작업이 끝나면 추가로 전달해
주세요.

| 상태 | 전달받을 값 | 사용 목적 |
|---|---|---|
| [ ] | X-Ray Collector IAM Role과 Pod Identity 적용 완료 여부 | Terraform 코드 작성 완료. 백엔드 트레이싱 전송 |
| [ ] | Grafana CloudWatch IAM Role과 Pod Identity 적용 완료 여부 | Terraform 코드 작성 완료. Grafana CloudWatch 조회 |
| [ ] | 서비스 VPC RDS Endpoint | 백엔드 DB 연결 |
| [ ] | RDS Secret 관리 방식 | 백엔드 DB 비밀번호 주입 |
