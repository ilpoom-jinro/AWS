"""
config.py — AIOps Agent 전용 설정

[MAS 정합]
- 공통 설정(AWS_REGION, DATABASE_URL 등)은 shared.config.SDKSettings가 담당.
- 이 파일은 AIOps Activity 동작에만 필요한 값을 보유.
- Bedrock 모델은 shared.bedrock.ClaudeModel Enum 사용 (여기서 모델 ID 하드코딩 안 함).
- AWS 자격증명은 IRSA/Pod Identity Default Credential Chain (직접 주입 금지).
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIOpsSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 다른 팀 환경변수와 충돌 방지
    )

    # EKS 컨텍스트 (entrypoint가 kubeconfig에 생성)
    OPS_KUBE_CONTEXT: str = Field(default="financial-ops-eks")
    SERVICE_KUBE_CONTEXT: str = Field(default="financial-service-eks")

    # 클러스터명 (DetectIncidentInput.cluster_name 매칭용)
    OPS_EKS_CLUSTER_NAME: str = Field(default="")
    SERVICE_EKS_CLUSTER_NAME: str = Field(default="")

    # AWS 리전 (service 클러스터 원격 접근 시 EKS describe/get-token에 사용)
    AWS_REGION: str = Field(default="ap-northeast-2")

    # Thanos Query (메트릭 수집, 읽기 전용) — 모니터링 스택 전환 반영
    THANOS_QUERY_URL: str = Field(
        default="http://observability-thanos-query.observability.svc.cluster.local:9090"
    )

    # 검증 대기 (Workflow timer가 사용)
    VERIFY_WAIT_SEC: int = Field(default=300)

    # 탐지 임계값
    CRASH_THRESHOLD: int = Field(default=3)
    PENDING_TIMEOUT_SEC: int = Field(default=600)

    # 자동 조치 최소 신뢰도 (미만이면 strategy=manual)
    RCA_CONFIDENCE_MIN: float = Field(default=0.7)

    # high_latency 탐지: Istio P95 요청 지연 임계값 (밀리초)
    # 상태 이상(CrashLoop 등)이 없는 Running 파드 중 P95 지연이 이 값을 넘으면 high_latency
    HIGH_LATENCY_P95_MS: float = Field(default=1000.0)

    # Temporal
    # 참고: 실제 Temporal 연결은 worker.py가 os.getenv("TEMPORAL_ADDRESS")로 수행한다
    # (Platform Core 소유 worker). 아래 필드는 로컬 테스트/호환용으로만 유지.
    TEMPORAL_HOST: str = Field(default="temporal-frontend.temporal.svc.cluster.local:7233")
    TEMPORAL_NAMESPACE: str = Field(default="default")
    TEMPORAL_TASK_QUEUE: str = Field(default="aiops-task-queue")


settings = AIOpsSettings()
