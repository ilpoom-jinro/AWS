# pinned 2026-07-01, controlled bump via scheduled EOL workflow
ARG MAS_BASE_IMAGE=python:3.12.13-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && curl -fsSL "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
        -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        "boto3" \
        "psycopg[binary]==3.2.3" \
        "pydantic-settings" \
        "sqlalchemy[asyncio]==2.0.41" \
        "asyncpg==0.30.0" \
        "temporalio==1.9.0"

# contracts / workflows / shared 는 Platform Core가 소유 — 함께 복사
COPY pods/aiops/orchestrator/app ./app
COPY shared ./shared
COPY contracts ./contracts
COPY workflows ./workflows

CMD ["python", "-m", "app.worker"]
