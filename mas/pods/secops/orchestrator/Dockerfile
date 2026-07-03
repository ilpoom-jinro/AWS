# pinned 2026-06-30, controlled bump via scheduled EOL workflow (#25)
ARG MAS_BASE_IMAGE=python:3.12.13-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

RUN pip install --no-cache-dir \
    "boto3" \
    "psycopg[binary]==3.2.3" \
    "pydantic-settings" \
    "temporalio==1.27.2" \
    "sqlalchemy[asyncio]==2.0.36" \
    "asyncpg==0.30.0"
    # temporalio: FinOps는 1.9.0 핀이나 1.9.0엔 temporalio.contrib.pydantic이 없어 SecOps가
    #   깨짐(검증됨). pydantic 데이터 컨버터가 포함된 1.27.2로 고정(requirements.txt와 동일).
    #   FinOps도 pydantic 컨버터 도입 시 1.27.2로 정렬 권장.
    # sqlalchemy[asyncio]/asyncpg: shared.audit.repository의 RDS 저장 경로(AUDIT_SINK=shared)에 필요.
    #   FinOps도 AuditLog 사용 시 공통 requirements.txt로 승격 조율.

# FinOps와 달리 SecOps 코드는 contracts/workflows도 import하므로 함께 복사
COPY pods/secops/orchestrator/app ./app
COPY shared ./shared
COPY contracts ./contracts
COPY workflows ./workflows

# 워커 실행 (FastAPI로 감싸려면 FinOps main.py 패턴 참고)
CMD ["python", "-m", "app.worker"]
