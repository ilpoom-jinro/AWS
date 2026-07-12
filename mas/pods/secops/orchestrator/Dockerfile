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
    "asyncpg==0.30.0" \
    "kubernetes==31.0.0" \
    "fastapi==0.115.6" \
    "uvicorn[standard]==0.34.0"
    # temporalio: 1.9.0엔 temporalio.contrib.pydantic이 없어 SecOps가 깨짐 → pydantic 컨버터가 포함된
    #   1.27.2로 고정(requirements.txt와 동일). FinOps도 pydantic 도입 시 1.27.2로 정렬 권장.
    # sqlalchemy[asyncio]/asyncpg: record_audit_log(RDS 전용, activities.platform) 저장 경로에 필요.
    # kubernetes: apply_isolation의 Istio AuthorizationPolicy 실제 apply에 필요.
    # fastapi/uvicorn: app.run이 띄우는 HTTP API(api.py) — UI 조회 + /health 프로브에 필요.

# SecOps는 contracts/workflows + activities(공통 platform.py 재-export)도 import하므로 함께 복사
#   (activities 미복사 시 `from activities.platform import record_audit_log`가 ImportError → CrashLoop)
COPY pods/secops/orchestrator/app ./app
COPY shared ./shared
COPY contracts ./contracts
COPY workflows ./workflows
COPY activities ./activities

# 워커 실행 (FastAPI로 감싸려면 FinOps main.py 패턴 참고)
CMD ["python", "-m", "app.run"]
