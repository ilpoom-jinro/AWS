# Temporal 배포 트러블슈팅 — 계정 이관 후 무인 기동까지

> **요약:** 새 AWS 계정(`609540154179`)으로 인프라를 이관한 뒤 Temporal이 안 떴다.
> 원인은 **"기존 클러스터엔 잔존 리소스가 있어 가려져 있던" 잠재 버그 6종**이 완전 새 클러스터에서 한꺼번에 표면화된 것.
> 전부 소스에 수정 반영 완료 → 이제 destroy/apply 시 무인 기동.
> **작성일:** 2026-06-30

---

## 1. 배경

- 무료 크레딧 소진으로 AWS 계정을 새로 이관(`797715838244` → `609540154179`).
- IaC(terraform)는 콜드스타트로 전부 재구축, GitOps(ArgoCD)로 플랫폼 배포.
- 인프라/EKS/RDS는 정상 기동했으나 **Temporal 파드만 계속 실패**.
- 증상이 한 겹 풀리면 다음 겹이 드러나는 식으로 **6개 이슈가 연쇄**로 나타남.

핵심 통찰: 아래 버그들은 **기존 클러스터에선 이전에 만들어진 리소스(시크릿/ConfigMap/DB/role)가 남아있어** 가려져 있었고, **완전히 빈 새 클러스터에서만** 드러났다.

---

## 2. 발견된 이슈 6종 + 해결 (의존 순서대로)

| # | 증상 | 근본 원인 | 해결 |
|---|------|-----------|------|
| 1 | ExternalSecret `could not get secret data from provider` | ESO Pod Identity IAM 정책이 `financial-*`/`velero/*`만 허용, **`temporal/*` 누락** → SM 접근 거부 | `vpc/ops/pod-identity.tf`에 `secret:temporal/*` ARN 추가 |
| 2 | schema가 `financial-service-db`로 붙어 timeout | Temporal Helm `connectAddr`가 **service RDS로 오지정**. 설계상 Temporal은 **ops RDS(`financial-ops-db`)** | `temporal/values.yaml` → `REPLACE_WITH_OPS_RDS_ENDPOINT`, ansible에 ops RDS 발견·치환 추가 |
| 3 | db-init Job이 `ContainerCreating` 무한대기 | Job(PreSync hook)이 마운트하는 ConfigMap이 일반 Sync-phase 리소스 → **PreSync 단계에 ConfigMap이 아직 없어 데드락** | (1차) ConfigMap도 PreSync hook으로 → (최종) **§3 재설계** 참조 |
| 4 | db-init이 `temporal_user` role 생성 실패 | SQL이 비번을 `DO $$ … $$` 블록 안에서 `:'temporal_pw'`로 주입하는데 **psql은 dollar-quote 블록 안에서 변수 보간을 안 함** → 문법에러 | role 생성을 `\gexec`(멱등), 비번은 블록 밖 `ALTER ROLE`로 동기화 |
| 5 | schema `no pg_hba.conf entry … no encryption (28000)` | ops RDS가 `rds.force_ssl`로 SSL 강제인데 **temporal-sql-tool/server가 TLS 없이 접속** | `temporal/values.yaml` 두 데이터스토어에 `tls.enabled=true, enableHostVerification=false` |
| 6 | prereqs가 `auto-sync will wipe out all resources`로 sync 거부 + 시크릿 깜빡임 | temporal-db-init의 **모든 리소스가 PreSync hook → 관리(non-hook) 리소스 0개** → ArgoCD prune 가드 + hook 재생성으로 시크릿이 사라졌다 생김 | **§3 재설계**: 전부 일반 리소스 + sync-wave |

> ⚠️ `600734575887`(ELB 서비스 계정)·`Project=ilpumjinro` 태그·`ilpumjinro.store` 도메인은 계정 무관 — 건드리지 않음.

---

## 3. temporal-db-init 구조 재설계 (이슈 #3·#6 최종 해결)

**문제였던 구조 (전부 hook):**

| 리소스 | 종류 | 어노테이션 |
|---|---|---|
| init-sql-configmap | ConfigMap | PreSync hook |
| external-secret-master | ExternalSecret | PreSync hook |
| external-secret-temporal | ExternalSecret | PreSync hook |
| job (db-init) | Job | PreSync hook |

→ 관리 리소스 0개라 ArgoCD `automated.prune`가 "모든 리소스를 지운다"고 보고 **sync 거부**. 또 ExternalSecret hook이 sync마다 재생성되어 **`temporal-rds-credentials` 시크릿이 깜빡** → 의존 파드 `CreateContainerConfigError`.

**해결한 구조 (전부 일반 리소스 + sync-wave):**

| 리소스 | 종류 | wave | 비고 |
|---|---|---|---|
| init-sql-configmap | ConfigMap | **-3** | 먼저 생성 |
| external-secret-master | ExternalSecret | **-2** | ESO가 시크릿 생성 |
| external-secret-temporal | ExternalSecret | **-2** | ESO가 시크릿 생성 |
| job (db-init) | Job | **-1** | `sync-options: Replace=true` |

핵심 원리: **순서는 hook이 아니라 sync-wave로 잡는다.** ArgoCD는 각 wave의 리소스가 Healthy가 될 때까지 기다린 뒤 다음 wave로 진행한다. ExternalSecret의 Healthy = `SecretSynced` = k8s 시크릿 생성 완료. 따라서 wave -1의 Job이 실행될 때 **ConfigMap과 시크릿이 이미 존재**한다 → 데드락·깜빡임 없음. Job은 spec.template이 불변이므로 `Replace=true`로 변경 시 삭제·재생성(멱등 SQL이라 안전).

---

## 4. 복구 중 적용한 수동 조치 (소스 수정이 반영되기 전까지의 임시 작업)

> 아래는 **이미 소스 수정으로 대체**되었으므로, 다음 배포부터는 자동으로 처리됨. 기록용.

- **클러스터 접근:** Teleport 인스턴스에 `aws ssm send-command`(비대화형)로 kubectl 실행. ArgoCD `selfHeal=true`라 수동 kubectl 패치는 즉시 원복되므로 **소스(Gitea) 수정이 정답**임을 확인.
- ops RDS에 `temporal`/`temporal_visibility` DB, `temporal_user` role, public 스키마 권한을 디버그 파드로 수동 생성 (→ 이슈 #4 수정으로 자동화).
- `temporal-rds-credentials`/`ops-rds-master` ExternalSecret을 hook 없는 일반 리소스로 수동 적용해 시크릿 안정화 (→ 이슈 #6 재설계로 자동화).

---

## 5. 최종 결과

```
temporal-frontend / history / matching / worker / web / admintools   1/1 Running
temporal-schema / temporal-namespace                                  Completed
ArgoCD `temporal` 앱                                                   Synced / Healthy
```

스키마는 ops RDS에 TLS로 접속해 1.19까지 정상 설치. Temporal Web UI도 기동.

---

## 6. 적용/배포 흐름 (참고)

GitOps 매니페스트는 **`financial/ansible-codebuild` 이미지에 baked-in**되고, `financial-gitops-bootstrap` CodeBuild(`NO_SOURCE`)가 그 이미지로 Gitea를 시드한다. 따라서 **매니페스트 수정은 다음 순서로만 반영**된다:

1. PR → `main` 머지
2. `ecr-images.yml` (`build_ansible_codebuild=true`)로 **ansible-codebuild 이미지 재빌드** ← 빠뜨리기 쉬움
3. `financial-gitops-bootstrap` CodeBuild 재실행 → Gitea 재시드
4. ArgoCD 자동 동기화

> 주의: gitops-bootstrap CodeBuild만 다시 돌리면 **옛 이미지**를 써서 수정이 반영 안 됨. 반드시 2번(이미지 재빌드) 선행.

---

## 7. 검증 권장

새 클러스터(또는 temporal 스택만 destroy 후 재배포)에서 무인 기동 확인:
- `temporal-prereqs` 앱이 Synced/Healthy로 가고 db-init Job이 1회 Completed 되는지
- `temporal-rds-credentials`/`ops-rds-master` 시크릿이 깜빡임 없이 안정 유지되는지
- `temporal` 앱 schema Job이 ops RDS에 TLS로 붙어 Completed → 서버 파드 Running 되는지

---

## 8. 관련 커밋

- 이슈 #1·#2·#3(1차)·#4: `main` (PR #428 + 후속 PR)
- 이슈 #5 (TLS): `fix: temporal SQL 데이터스토어에 TLS 활성화`
- 이슈 #3·#6 최종 (hook 재설계): `fix: temporal-db-init을 hook 대신 일반 리소스+sync-wave로 재설계`
