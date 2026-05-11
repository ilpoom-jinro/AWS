# 금융권 멀티클라우드 통합 관제 플랫폼 - AWS

> 2026년 4월 망분리 규제 완화를 선제 적용한 **하이브리드 CMP/IDP** 구축 프로젝트입니다.
>
> AI 멀티 에이전트 시스템(MAS)이 비용 이상·장애·보안 위협을 자율 탐지·분석·조치하고,  
> 사람은 Slack HITL 승인 게이트에서 **최종 결정만** 합니다.

---

## 개요

금융권 클라우드 전환 현장에서 반복되는 3가지 문제를 해결합니다.

| 영역 | AS-IS | TO-BE | 개선율 |
|------|-------|-------|--------|
| **FinOps** 비용 이상 대응 | 4.5시간 (수동) | 15분 이내 | -95% |
| **AIOps** 장애 복구 (MTTR) | 2.3시간 | 30분 이내 | -78% |
| **SecOps** 보안 위반 대응 | 45분 | 5분 이내 | -89% |
| 인프라 변경 리드타임 | 3~5일 | 1시간 이내 | -95% |
| 분기 감사 보고서 작성 | 16시간 | 10분 (자동) | -99% |
| 월 오버프로비저닝 비용 | $2,400 | $800 이하 | -67% |

### Pain Points: 왜 지금, 왜 이 플랫폼인가

일반 기업은 Datadog·Grafana Cloud 같은 SaaS 모니터링을 붙이면 되지만, 금융권은 『전자금융감독규정 제14조의2·제15조』 망분리 규제로 인해 클라우드 기반 SaaS 툴 자체를 올릴 수 없었습니다. 결과적으로 모니터링·분석·자동화 도구를 전부 직접 구축하거나 수작업으로 처리해야 했습니다.

**2026년 4월, 금융위원회 규제 완화로 내부 업무용 SaaS의 클라우드 탑재가 허용되었습니다.**  
이 변화가 이 프로젝트의 출발점입니다.

> **핵심 원칙**: 고객 개인정보(PII)는 온프레미스에 완전 격리 — 클라우드로 나가는 건 인프라 헬스 메트릭과 운영 로그뿐입니다.

---

## 아키텍처

### 하이브리드 클라우드 구성

```
┌─────────────────────────────────────────────────────────────┐
│          On-Prem / Oracle Cloud (시뮬레이션)                 │
│  ┌──────────────────────┐  ┌──────────────────────────────┐  │
│  │  개인정보 DB (폐쇄망) │  │  Headscale Control Plane     │ │
│  │  - PII 완전 격리      │  │  - VPN 중앙 관리             │ │
│  │  - 단방향 메트릭 전송 │  └──────────────────────────────┘ │
│  └──────────────────────┘                                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ VPN Tunnel (Tailscale)
            ┌──────────────┴──────────────┐
            │                             │
   ┌────────▼────────┐          ┌─────────▼──────────┐
   │      AWS        │          │        GCP         │
   │  EKS HA (Main)  │◀────────▶│  GKE Cluster (DR)│
   │  AI Agent Layer │  Failover│  Standby / 관제    │
   └─────────────────┘          └────────────────────┘
```

### MAS (멀티 에이전트 시스템) 레이어

```
탐지 → 분석 → 생성/검증 → HITL 승인 → 실행 → 감사 기록

[Prometheus / CloudTrail / VPC Flow Logs]
             │
     ┌───────▼────────┐
     │ 이상 탐지 Agent│  (읽기 전용)
     └───────┬────────┘
             │ 이벤트 발행
  ┌──────────┴────────────────┐
  │                           │
┌─▼──────────┐        ┌──────▼────────┐
│ 비용 분석  │        │  장애 분석    │  ← Bedrock (PrivateLink)
│ Agent      │        │  Agent        │    LangGraph 추론 루프
└─────┬──────┘        └──────┬────────┘
      │                       │
┌─────▼───────────────────────▼──────┐
│     IaC 생성 Agent (Terraform HCL) │
│     IaC 검증 Agent (Actor-Critic)  │
└─────────────────┬──────────────────┘
                  │
         ┌────────▼────────┐
         │  Slack HITL 게이트 │  ← 사람이 최종 승인
         └────────┬────────┘
                  │ 승인
         ┌────────▼────────┐
         │  Temporal 실행   │  → terraform apply / kubectl
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │ RDS PostgreSQL  │  ← 전체 의사결정 이력 영구 저장
         └─────────────────┘
```

---

## 핵심 아키텍처 결정

### AI 두뇌: Amazon Bedrock + PrivateLink

EKS 내 에이전트가 퍼블릭 인터넷을 경유하지 않고 AWS VPC 내부망(PrivateLink)을 통해서만 LLM을 호출합니다. 『전자금융감독규정 제15조(망분리)』를 완벽 충족합니다.

| 모델 | 용도 |
|------|------|
| Claude 3 Haiku | 단순 파싱·분류·탐지 (경량·저비용) |
| Claude 3.5 Sonnet | 복잡한 코드 생성·근본 원인 추론 (고성능) |

### MAS 오케스트레이션: Temporal + LangGraph 하이브리드

| 프레임워크 | 레벨 | 역할 |
|------------|------|------|
| **Temporal** (척추) | Macro | 전체 파이프라인 뼈대. 워크플로우 실행 보장, 자동 재시도, 거시적 상태 통제 |
| **LangGraph** (두뇌) | Micro | 단일 노드 내 Agent 간 다단계 추론 루프 제어 (IaC 생성 ↔ 검증 Actor-Critic) |

### 데이터베이스: RDS PostgreSQL Multi-AZ

LangGraph 대화 이력·인프라 메트릭·감사 로그를 JSONB로 효율 저장. EKS 내부 컨테이너 DB 대신 완전 관리형으로 단일 장애점(SPOF) 제거 및 금융권 수준 고가용성 확보.

---

## 3대 핵심 자동화 시나리오

> **공통 원칙**: 모든 시나리오는 AI가 제안하고 사람이 승인하는 **HITL(Human-in-the-Loop)** 구조입니다.

### 시나리오 A — FinOps: 비용 이상 탐지 및 자동 최적화

```
이상 탐지 Agent (CPU 12% 감지)
    → 비용 분석 Agent (원인 파악, 최적화 방안)
    → IaC 생성 Agent (t3.large → t3.medium .tf 초안)
    → IaC 검증 Agent (HA·보안 교차 검증, Actor-Critic 루프)
    → Slack HITL (예상 절감 $120/월 + 검증된 코드 전송)
    → 승인 시 terraform apply → 월 $120 절감
    → RDS 감사 이력 저장
```

### 시나리오 B — AIOps: 지능형 장애 탐지 및 운영 자동화

```
이상 탐지 Agent (Pod CrashLoop 감지)
    → 장애 분석 Agent (LangGraph 루프: OOMKilled 원인 추론)
    → 조치 방안 제안 (파드 재시작 / 스케일 아웃 / 롤백 우선순위)
    → Slack HITL 승인
    → Temporal 실행 (kubectl / terraform apply)
    → 배포 후 5분 집중 모니터링
    → 이상 재감지 시 Git 기반 자동 롤백 트리거
```

### 시나리오 C — SecOps: 망분리 규제 위반 감지 및 eBPF 차단

```
보안 탐지 Agent (비정상 Outbound 연결 감지)
    → 보안 분석 Agent (전자금융감독규정 위반 여부 자동 매핑)
    → 보안 검증 Agent (Blast Radius 분석: 오탐 여부 시뮬레이션)
    → Slack 긴급 HITL 승인
    → Cilium(eBPF) 정책 즉시 적용 → 격리
    → 금융 규제 보고서 JSONB 자동 포맷팅 → RDS 영구 저장
```

> Cilium 선택 이유: 기본 K8s NetworkPolicy는 L3/L4만 지원하지만, Cilium은 eBPF 기반 L7 정책 및 프로세스 단위 가시성으로 금융권 수준의 세밀한 트래픽 제어가 가능합니다.

---

## 기술 스택

| 레이어 | 기술 | 용도 |
|--------|------|------|
| **클라우드** | AWS EKS, GCP GKE, Oracle Cloud | 멀티클라우드 + 하이브리드 인프라 |
| **오케스트레이션** | Temporal, LangGraph | MAS 워크플로우 조율 |
| **AI/LLM** | Amazon Bedrock (Claude 3 Haiku / Sonnet) | Agent 추론 엔진 |
| **데이터베이스** | RDS PostgreSQL Multi-AZ, Redis | 상태 관리 및 감사 로그 |
| **모니터링** | Prometheus, Grafana, Kubecost | 메트릭 수집 및 시각화 |
| **IaC** | Terraform, ArgoCD | 인프라 코드화 및 GitOps |
| **보안** | Cilium (eBPF), VPC Flow Logs, CloudTrail | 네트워크 정책 및 감사 |
| **백업** | Velero, RDS Snapshots, S3 Versioning | 재해 복구 |
| **VPN** | Headscale, Tailscale | 멀티클라우드 보안 통신 |
| **프론트엔드** | Next.js + Grafana iframe | 통합 운영 포털 |
| **협업** | Slack, GitHub | HITL 승인 및 코드 관리 |

---

## 구축 현황

| 환경 | 상태 | 내용 |
|------|------|------|
| AWS EKS | 🔄 구성 중 | Main 서비스 (AI Agent, CMP) |
| GCP VPC/서브넷/방화벽 | ✅ 완료 | DR 클러스터 기반 구성 |
| Oracle Cloud Headscale | ✅ 완료 | VPN Control Plane 구축 |
| VPN 터널링 | ✅ 완료 | AWS/GCP Tailscale ↔ Oracle Headscale |
| GKE 클러스터 | 🔄 진행 중 | 보안 요소 추가 작업 |
| On-Prem 시뮬레이션 | 🔄 진행 중 | Oracle Cloud 폐쇄망 환경 구성 |

---

## 백업 정책

| 대상 | 방식 | 주기 | 보관 |
|------|------|------|------|
| RDS PostgreSQL | Automated Snapshot | 일 1회 03:00 UTC | 7일 |
| RDS PostgreSQL | Manual Snapshot | 주 1회 (일요일) | 30일 |
| EKS ETCD 상태 | Velero + S3 | 일 2회 (06:00, 18:00) | 14일 |
| Terraform State | S3 Versioning | 변경 시마다 | 무제한 |
| Redis | RDB Snapshot | 6시간마다 | 48시간 |
| Agent 설정 파일 | GitOps | 변경 시마다 | Git 이력 보존 |

---

## 프로젝트 범위

| ✅ 할 것 | ❌ 하지 않을 것 |
|----------|----------------|
| 비용 이상 탐지 → 최적화 자동화 (FinOps) | 실제 금융사 production 트래픽 처리 |
| 장애 탐지 → 원인 분석 → 자동 대응 (AIOps) | 고유식별정보·개인신용정보 처리 |
| 보안 위반 감지 → eBPF 차단 (SecOps) | SLA/SLO 기반 성능 보장 계약 |
| AWS EKS HA + 오토스케일링 클러스터 구축 | 단일 Agent 대비 정량 벤치마크 |
| GCP VPC + Headscale VPN + GKE 구축 | Azure 클러스터 직접 운영 |
| Oracle Cloud 온프레미스 시뮬레이션 | |
| Temporal 오케스트레이터 기반 워크플로우 | |
| Slack HITL 승인 게이트 | |
| RDS PostgreSQL Multi-AZ 감사 로그 | |
| DR Failover 시뮬레이션 (AWS → GCP) | |
| Grafana + Next.js 통합 대시보드 | |

---

## 팀 R&R

| 역할 | 이름 | 주요 책임 |
|------|------|----------|
| AWS - SRE | 백준호 | 전체 시스템 안정성 관리 |
| AWS - 인프라 리드 | 신봉근 | AWS 인프라 설계 및 구축 총괄 |
| AWS - 플랫폼 엔지니어 | 이준영 | 컨테이너 플랫폼 운영 |
| AWS - 보안 엔지니어 | 조다현 | 보안 정책 및 컴플라이언스 |
| GCP - IaC, VPN | 김경한 | GCP 기본 인프라 구축 |
| GCP - K8s, CI/CD | 허상준 | GKE 클러스터 및 배포 파이프라인 |
| On-Prem - DB, Oracle Cloud | 김민수 | 온프레미스 시뮬레이션 환경 |

---

## 로드맵

- [ ] AWS EKS HA 클러스터 구축 완료
- [ ] Temporal + LangGraph MAS 파이프라인 구현
- [ ] FinOps 시나리오 A E2E 검증
- [ ] AIOps 시나리오 B E2E 검증 (Chaos Mesh 장애 주입)
- [ ] SecOps 시나리오 C E2E 검증
- [ ] Next.js 통합 포털 대시보드
- [ ] DR Failover 시뮬레이션 (AWS Active → GCP Standby)
- [ ] 금융 규제 보고서 자동 생성 검증

---

## 관련 레포지토리

| 레포 | 설명 |
|------|------|
| [AWS (현재)](https://github.com/JunYoungLee260/AWS) | Main 서비스 — AI Agent, CMP/IDP 핵심 |
| GCP_sub | GCP DR 클러스터 및 VPN 구성 |

---

## 참고

- 벤치마킹: [메가존 SpaceONE](https://spaceone.org/) — 임직원용 멀티클라우드 통합 운영 포털
- 규제 근거: 전자금융감독규정 제14조의2, 제15조 (2026년 4월 완화)
- 문서 버전: 2차 멘토링 최종 기획안 v1 (2026-05-07)
