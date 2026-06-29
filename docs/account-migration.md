# 계정 이관 런북 — `797715838244` → `609540154179`

> 대상 리전: `ap-northeast-2` / 전략: **새 계정 신규 구축(`-v4` 버킷), 옛 계정 보존**
> 코드 사전작업은 브랜치 `chore/account-migration-609540154179`에서 완료됨.

---

## 0. 이번 코드 변경으로 끝난 것 (재작업 불필요)

| 항목 | 처리 |
|---|---|
| state/CloudTrail/Teleport 버킷명 충돌 | `ilpumjinro-*-v3` → **`-v4`** 로 일괄 변경 (전역 고유명 회피) |
| 옛 계정 ID 하드코딩 4곳 | `REPLACE_WITH_ACCOUNT_ID` / `REPLACE_WITH_ECR_REGISTRY` placeholder로 전환 |
| ansible 치환 dict | `REPLACE_WITH_ACCOUNT_ID` 키 추가 (ALB 로그 버킷명용) |
| IaC 본체 계정 참조 | 원래부터 `data.aws_caller_identity`로 동적 → **수정 불필요** |

> ✅ 해결됨: IAM 정책에 옛 `-v2` 버킷명이 남아있던 2곳도 `-v4`로 정정 (`iam/github-oidc.tf` state 버킷, `teleport-s3.tf` 세션 버킷). 이전엔 버킷이 v2→v3로 올라갈 때 정책이 갱신 안 돼 실제 버킷명과 어긋나 있었음.

---

## 1. 사전 준비 (Pre-req)

- [ ] 새 계정 `609540154179` 루트/관리자 접근 확보
- [ ] **로컬에 새 계정 자격증명** 세팅 (`aws sts get-caller-identity`로 `609540154179` 확인) — 현재 옛 계정 토큰은 만료/무효 상태
- [ ] 도메인 `ilpumjinro.store` 처리 방침 결정 (Route53 Hosted Zone 신규 생성 + NS 위임 변경 / 또는 기존 유지)
- [ ] 이관 중 옛 계정 리소스는 그대로 둠 (롤백 안전망)

---

## 2. 부트스트랩 (로컬 apply — chicken-egg 해소)

`bootstrap/`는 백엔드가 없어 **local state**로 동작 → 원격 state 버킷(`-v4`)을 먼저 만든다.

```bash
cd bootstrap
terraform init
terraform apply        # ilpumjinro-terraform-state-v4, -cloudtrail-logs-locked-v4, -teleport-v4 생성
```

- [ ] `ilpumjinro-terraform-state-v4` (state, Object Lock/버전닝)
- [ ] `ilpumjinro-cloudtrail-logs-locked-v4` (CloudTrail, Object Lock)
- [ ] `ilpumjinro-teleport-v4`

---

## 3. 원격 백엔드 초기화 + OIDC 역할 생성 (로컬)

루트/`kms` 모두 backend가 `-v4`를 가리키도록 변경됨 → 새 빈 백엔드로 init.

```bash
cd ..
terraform init -reconfigure          # ilpumjinro-terraform-state-v4 사용
# OIDC provider + github-actions 역할 먼저 생성 (CI 인증 부트스트랩)
terraform apply -target=aws_iam_openid_connect_provider.github \
                -target=aws_iam_role.github_actions
```

- [ ] `aws_iam_openid_connect_provider.github`
- [ ] `aws_iam_role.github_actions` (이름: `ilpumjinro-github-actions-role`)
- [ ] 생성된 역할 ARN 기록: `arn:aws:iam::609540154179:role/ilpumjinro-github-actions-role`

---

## 4. GitHub Secrets 갱신

워크플로우 8개 전부 **`AWS_ROLE_ARN_DEV`** 를 참조 (`PR-terraform-plan`, `packer-ami`, `terraform-operations`, `app-deploy`, `ecr-images`, `monitoring-images`, `pii-image-build`, `mas-agent-deploy`).

```bash
gh secret set AWS_ROLE_ARN_DEV --body "arn:aws:iam::609540154179:role/ilpumjinro-github-actions-role"
# AWS_ROLE_ARN 시크릿이 별도로 존재하면 동일 값으로 같이 갱신
```

- [ ] `AWS_ROLE_ARN_DEV` 갱신
- [ ] (있으면) `AWS_ROLE_ARN` 갱신

---

## 5. 전체 인프라 apply

OIDC 역할이 생겼으므로 이후는 CI(`terraform-operations.yml`) 또는 로컬로 전체 적용.

```bash
terraform apply        # VPC×3, EKS×2, RDS, VPC Endpoint, security/siem, route53 ...
```

- [ ] VPC(globalservice/ops/service) + EKS 클러스터 2개 + 노드그룹
- [ ] RDS (single_az_mode 값 확인 — 운영 전환 시 false)
- [ ] security 모듈 (CloudTrail `-v4`, SIEM Athena, anomaly detection)
- [ ] Route53 / ACM (8번 참고)

---

## 6. ECR 이미지 이관 (51개 repo)

새 계정엔 빈 ECR repo만 생김 → 이미지 채워야 GitOps/노드가 pull 가능.

**방법 A — 재빌드 (CI 재실행, 권장: 소스가 있으므로 깔끔)**
- [ ] `ecr-images.yml`, `monitoring-images.yml`, `pii-image-build.yml`, `mas-agent-deploy.yml` 재실행

**방법 B — 크로스 계정 복사 (재빌드 비용 큰 외부 미러 이미지: trivy-db 등)**
```bash
# 옛 계정에 임시 repository policy로 새 계정 pull 허용 후
crane copy 797715838244.dkr.ecr.ap-northeast-2.amazonaws.com/<repo>:<tag> \
           609540154179.dkr.ecr.ap-northeast-2.amazonaws.com/<repo>:<tag>
# 또는 skopeo copy docker://... docker://...
```

---

## 7. Packer AMI 재빌드

AMI는 계정 종속(공유 안 하면 새 계정에 없음). [`packer-ami.yml`](../.github/workflows/packer-ami.yml) 재실행.

- [ ] `teleport-k3s` AMI 새 계정에서 빌드 → `packer/manifest.json` 갱신 확인

---

## 8. GitOps 플랫폼 부트스트랩

ansible/buildspec이 `REPLACE_WITH_*`를 **새 계정 값으로 자동 치환** (이번 코드 변경으로 ALB 버킷·temporal-db-init 이미지도 자동 해소).

- [ ] `buildspec-gitops-bootstrap` 실행 → Gitea seed push → ArgoCD 동기화
- [ ] ArgoCD Application 전부 `Synced/Healthy` 확인 (특히 `temporal`, `aws-load-balancer-controller-service`, ALB 로그 버킷 `financial-alb-access-logs-609540154179`)

---

## 9. 데이터 이관 (필요 시)

- [ ] RDS: 옛 계정에 운영 데이터가 있으면 snapshot 공유 → 새 계정 복원 (없으면 skip)
- [ ] ExternalSecrets/Secrets Manager 시크릿 값 재투입
- [ ] S3 데이터(velero 백업 등) 필요 시 크로스 계정 복사

---

## 10. DNS / 인증서

- [ ] Route53 `ilpumjinro.store` Hosted Zone 처리 + NS 위임
- [ ] ACM `*.ilpumjinro.store` 인증서 새 계정 재발급 + DNS 검증
- [ ] Route53 Failover(PRIMARY AWS / SECONDARY GCP) 레코드 새 ALB/IP로 갱신

---

## 11. 검증 & 컷오버

- [ ] `aws sts get-caller-identity` → `609540154179`
- [ ] `kubectl get applications -n argocd` 전부 정상
- [ ] 데모앱/포털 외부 접속 + ALB access log가 `-609540154179` 버킷에 적재
- [ ] CloudTrail → `-v4` 버킷 적재, Athena 쿼리 동작
- [ ] 안정화 후 옛 계정 `797715838244` 리소스 정리(destroy) — **마지막 단계**

---

### 부록 — 옛 계정 관련 잔존 참조 (코드)
- `Project = "ilpumjinro"` 태그, `ilpumjinro.store` 도메인 → 계정 무관, 변경 불필요
- `600734575887` → AWS 소유 ELB 서비스 계정(서울), **고정값, 절대 변경 금지**
