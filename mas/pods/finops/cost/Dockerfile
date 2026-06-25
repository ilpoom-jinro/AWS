ARG MAS_BASE_IMAGE=python:3.12-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "awscli==1.36.40" "boto3" "psycopg[binary]==3.2.3" "pydantic-settings" "temporalio==1.9.0"

COPY pods/finops/agents/app ./app
COPY pods/finops/cost/app/agent_logic.py ./app/agent_logic.py
COPY shared ./shared
COPY contracts ./contracts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
