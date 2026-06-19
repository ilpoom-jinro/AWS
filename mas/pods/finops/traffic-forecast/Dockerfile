ARG MAS_BASE_IMAGE=python:3.12-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

RUN pip install --no-cache-dir "temporalio==1.9.0"

COPY pods/finops/agents/app ./app
COPY pods/finops/orchestrator/app/agent_runtime.py ./app/agent_runtime.py

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
