# 작성자 : 김민수
# 최종 수정일 : 6월 13일
# 계속 수정하면서 진행하겠습니다 ..

# contracts

MAS Platform Core에서 정의하는 공통 계약(Contract) 레이어입니다.

모든 Agent(FinOps, AIOps, SecOps)는 이 패키지에 정의된 모델과 인터페이스를 기준으로 구현해 주시기 바랍니다.

---

# 목적

`contracts`는 Agent 간 통신에 사용되는 데이터 모델과 Activity 인터페이스를 정의합니다.

본 패키지는 아래 원칙을 따릅니다.

* 순수 계약 레이어
* Temporal Runtime 의존성 없음
* LangGraph 의존성 없음
* AWS SDK 의존성 없음
* Agent 구현체 의존성 없음

`contracts`는 시스템 전체에서 가장 안정적인 계층으로 유지하는 것을 목표로 합니다.

---

# 파일 구조

```text
contracts/
├── README.md               # Contract Specification
├── models.py               # Pydantic 기반 공통 모델
└── activity_interfaces.py  # Activity Protocol 정의
```

| 파일                     | 설명                      |
| ---------------------- | ----------------------- |
| models.py              | Agent 간 전달되는 공통 데이터 모델  |
| activity_interfaces.py | Activity 인터페이스 정의       |
| README.md              | Contract 명세 문서          |

---

# 레이어 구조

```text
contracts/                        ← 순수 계약 (temporalio 의존성 없음)
    ↑
workflows/activity_options.py     ← 실행 정책
    ↑
workflows/*.py                    ← Workflow 구현체
    ↑
agents/*/                         ← Agent 구현체
```

## 의존성 규칙

`contracts`는 상위 계층을 참조하지 않습니다.

허용 예시:

```python
from pydantic import BaseModel
```

금지 예시:

```python
from temporalio import ...
from langgraph import ...
from boto3 import ...
```

---

# 전체 데이터 흐름

Agent Workflow는 아래 순서로 진행됩니다.

```text
Workflow
    ↓
Activity Input 생성                              ← CollectMetricsInput / DetectIncidentInput / DetectThreatInput
    ↓
수집/탐지 Activity 실행
    ↓
Root Model 생성 (workflow_id 생성 시점)           ← MetricsInput / IncidentContext / SecurityEvent
    ↓
분석 결과 생성                                    ← AnomalyReport
    ↓
Plan 생성                                        ← TerraformPlan / RemediationPlan / RegulationMapping
    ↓
ApprovalRequest 생성
    ↓
ApprovalResult 생성
    ↓
ExecutionResult 생성
    ↓
AuditLog 저장
```

---

# workflow_id 전파 규칙

`workflow_id`는 하나의 Workflow 실행 전체를 추적하기 위한 식별자입니다.

Audit Log, Approval Tracking, Execution History, Redis Event Stream 등 모든 E2E 추적은 `workflow_id`를 기준으로 연결됩니다.

---

## Root 모델

`workflow_id`를 생성하는 모델은 아래 세 개뿐입니다.

| 모델                | 시나리오   |
| ----------------- | ------ |
| `MetricsInput`    | FinOps |
| `IncidentContext` | AIOps  |
| `SecurityEvent`   | SecOps |

생성 방식:

```python
workflow_id: str = Field(default_factory=new_workflow_id)
```

## Root 모델 생성 시점

Root 모델은 Workflow가 직접 생성하지 않습니다.

탐지/수집 Activity가 외부 시스템으로부터 데이터를 수집한 후 생성합니다.

```text
CollectMetricsInput → collect_metrics()  → MetricsInput 생성
DetectIncidentInput → detect_incident()  → IncidentContext 생성
DetectThreatInput   → detect_threat()    → SecurityEvent 생성
```

생성된 `workflow_id`는 이후 모든 Derived 모델로 전파됩니다.

---

## Derived 모델

Root 모델 이후 생성되는 모든 모델은 상위 모델의 `workflow_id`를 그대로 전달받아야 합니다.

새로운 `workflow_id`를 생성하지 않습니다.

```text
MetricsInput
    ↓
AnomalyReport
    ↓
TerraformPlan
    ↓
ApprovalRequest
    ↓
ApprovalResult
    ↓
ExecutionResult
    ↓
AuditLog
```

### 올바른 예

```python
plan = TerraformPlan(
    workflow_id=report.workflow_id,
    hcl_content="...",
)
```

### 잘못된 예

```python
plan = TerraformPlan(
    workflow_id=new_workflow_id(),
    hcl_content="...",
)
```

새로운 `workflow_id`를 생성하면 E2E 추적 체인이 끊어질 수 있습니다.

---

## Derived 모델 목록

아래 모델은 반드시 상위 모델의 `workflow_id`를 전달받아야 합니다.

```text
AnomalyReport
TerraformPlan
RemediationPlan
RecoveryVerification
RegulationMapping
ComplianceReport
ApprovalRequest
ApprovalResult
AuditLog
ExecutionResult
```

---

# AuditLog Payload 규칙

`AuditLog.payload`는 `dict[str, Any]` 타입으로 정의되어 있습니다.

타입만으로는 구조를 강제할 수 없으므로 아래 규칙을 준수해 주시기 바랍니다.

---

## event_type별 payload 규칙

| event_type           | payload 필수 키 | 값                              |
| -------------------- | ------------ | ------------------------------ |
| `workflow_started`   | `input`      | Root 모델 `.model_dump()`        |
| `anomaly_detected`   | `report`     | `AnomalyReport.model_dump()`   |
| `analysis_completed` | `report`     | `AnomalyReport.model_dump()`   |
| `iac_generated`      | `plan`       | `TerraformPlan.model_dump()`   |
| `approval_requested` | `request`    | `ApprovalRequest.model_dump()` |
| `approval_granted`   | `result`     | `ApprovalResult.model_dump()`  |
| `approval_denied`    | `result`     | `ApprovalResult.model_dump()`  |
| `approval_timeout`   | `result`     | `ApprovalResult.model_dump()`  |
| `action_executed`    | `result`     | `ExecutionResult.model_dump()` |
| `rollback_triggered` | `plan`       | `RemediationPlan.model_dump()` |
| `workflow_completed` | `summary`    | `str`                          |
| `workflow_failed`    | `error`      | `str`                          |

### 올바른 예

```python
AuditLog(
    workflow_id=request.workflow_id,
    scenario="finops",
    event_type="approval_requested",
    actor="finops-workflow",
    summary="Terraform Plan 승인 요청",
    payload={
        "request": request.model_dump()
    },
)
```

### 잘못된 예

```python
payload={"data": request.model_dump()}
```

```python
payload={"plan": request.model_dump()}
```

`event_type`과 payload 키는 반드시 일치해야 합니다.

---

# 시나리오별 플랜 매핑 규칙

`ApprovalRequest`와 `AnomalyReport`에는 Validator가 존재합니다.

시나리오와 플랜이 일치하지 않으면 Validation Error가 발생합니다.

시나리오-Plan 매핑은 `models.py`의 `PLAN_FIELD_BY_SCENARIO` 상수로 관리됩니다. `ApprovalRequest`와 `AnomalyReport`의 Validator는 이 상수를 참조합니다.

| scenario | 허용 필드                | 금지 필드                                    |
| -------- | -------------------- | ---------------------------------------- |
| `finops` | `terraform_plan`     | `remediation_plan`, `regulation_mapping` |
| `aiops`  | `remediation_plan`   | `terraform_plan`, `regulation_mapping`   |
| `secops` | `regulation_mapping` | `terraform_plan`, `remediation_plan`     |

---

## ApprovalRequest 규칙

승인 요청은 반드시 승인 대상이 존재해야 합니다.

```python
# 잘못된 예
ApprovalRequest(
    scenario="finops",
)
```

```python
# 올바른 예
ApprovalRequest(
    scenario="finops",
    terraform_plan=plan,
)
```

---

## AnomalyReport 규칙

분석 단계에서는 플랜 없이 보고서만 생성하는 경우가 있으므로 플랜 누락을 허용합니다.

```python
AnomalyReport(
    scenario="finops",
    ...
)
```

다만 시나리오와 일치하지 않는 플랜은 허용되지 않습니다.

---

## 시나리오 추가 시 수정 지점

새로운 시나리오가 추가될 경우 아래 항목을 함께 수정해 주시기 바랍니다.

```text
1. ScenarioType Literal
2. models.py의 PLAN_FIELD_BY_SCENARIO        ← 이것만 수정하면 Validator는 자동 반영
3. README.md 시나리오별 플랜 매핑 규칙
4. activity_interfaces.py Activity Interface
```

---

# Activity Input 모델

탐지 및 수집 Activity는 외부 시스템으로부터 데이터를 수집하는 진입점 역할을 합니다.

Workflow에서 아래 모델을 생성하여 Activity에 전달합니다.

| 모델                              | 시나리오   | 대응 Activity                  |
| ------------------------------- | ------ | ---------------------------- |
| `CollectMetricsInput`           | FinOps | `collect_metrics`            |
| `DetectIncidentInput`           | AIOps  | `detect_incident`            |
| `DetectThreatInput`             | SecOps | `detect_threat`              |
| `GenerateComplianceReportInput` | SecOps | `generate_compliance_report` |

---

# 제약 사항

## IncidentContext.recent_logs

`recent_logs`는 최대 50개 로그만 저장합니다.

* Temporal Payload 크기 제한 대응 (단일 payload 2MB)
* LangGraph Context 과도 증가 방지
* RCA 수행에 필요한 최소 로그 유지

전체 로그는 Loki / S3 / CloudWatch Logs 등 외부 저장소를 사용해 주시기 바랍니다.

## SecurityEvent.namespace

현재 SecOps 시나리오 설계 기준으로 필수 필드입니다.

VPC 레벨 탐지는 `vpc_id` 단위로 수행되며, `namespace`는 탐지 후 구현체에서 채웁니다.

> SecOps 1차 구현 완료 후 필드 검증 방식을 재검토할 예정입니다.

---

# Activity 구현 규칙

## 입출력 규칙

Activity 입출력은 반드시 `contracts/models.py`에 정의된 모델을 사용해 주시기 바랍니다.

허용 예시:

```python
async def collect_metrics(
    input: CollectMetricsInput,
) -> MetricsInput:
```

금지 예시:

```python
async def collect_metrics(
    input: dict,
) -> dict:
```

---

## LangGraph 반환 규칙

LangGraph 내부 State를 외부 계약 모델 대신 직접 반환하지 않습니다.

허용 예시:

```python
return RemediationPlan(...)
```

금지 예시:

```python
return state
```

---

# Error Handling 규칙

Temporal RetryPolicy와 충돌하지 않도록 구현해 주시기 바랍니다.

---

## 재시도 가능한 오류

아래 유형의 오류는 그대로 발생시키는 것을 권장합니다.

* Network Error
* Timeout
* Throttling
* 일시적인 외부 시스템 장애

해당 오류는 Temporal RetryPolicy가 처리합니다.

---

## 재시도 불가 오류

아래 유형의 오류는 non-retryable 처리하는 것을 권장합니다.

* Contract Validation Error
* Business Rule 위반
* 잘못된 입력값
* 시나리오 매핑 오류

예시:

```python
raise ApplicationError(
    "invalid request",
    non_retryable=True,
)
```

---

## 금지 사항

Activity 내부에서 직접 재시도 로직을 구현하지 않습니다.

```python
for retry in range(3):
    ...
```

```python
while True:
    ...
```

Retry는 Temporal에서 관리합니다.

---

# Timeout 및 RetryPolicy

본 패키지는 Timeout 및 RetryPolicy를 관리하지 않습니다.

실행 정책은 `workflows/activity_options.py`에서 관리합니다.

---

# CONTRACT_VERSION

현재 버전:

```text
v1
```

Contract Version은 하위 호환성 검증을 위해 사용합니다.

버전 불일치 시 에러 대신 Warning 로그를 남기는 Soft Validation 방식을 사용합니다.

---

## 버전 변경 기준

아래 변경은 버전 증가를 권장합니다.

* 필드 삭제
* 필드 타입 변경
* 기존 Derived 모델을 깨뜨리는 필수 필드 추가
* 기존 데이터 생성 또는 수신을 깨뜨리는 Validator 변경

---

## 버전 변경 없이 허용

* Optional 필드 추가
* 신규 모델 추가
* 하위 호환성을 유지하는 Validator 추가

---

## 필드 변경 협의 규칙

| 변경 종류          | 처리         |
| -------------- | ---------- |
| Optional 필드 추가 | 허용         |
| 신규 모델 추가       | 허용         |
| 필드 삭제          | 팀 전체 합의 필요 |
| 필드 타입 변경       | 팀 전체 합의 필요 |
| Enum 값 변경      | 팀 전체 합의 필요 |

---

# 모델 파일 분리 기준

현재 모든 모델은 `contracts/models.py`에 위치하고 있습니다.

아래 조건 중 하나라도 충족되면 시나리오별 파일 분리를 진행하겠습니다.

* models.py 700줄 초과
* 시나리오별 필드 확장 증가
* 팀 간 동시 수정 충돌 발생

예시 구조:

```text
contracts/
├── models.py
├── finops_models.py
├── aiops_models.py
├── secops_models.py
└── activity_interfaces.py
```

---

# 설계 원칙

Contract의 안정성을 최우선으로 합니다.

```text
1. Contract 안정성
2. E2E 추적 가능성
3. 구현 편의성
4. 기능 확장성
```

새로운 Agent가 추가되더라도 기존 Contract는 최대한 유지하는 방향으로 설계해 주시기 바랍니다.