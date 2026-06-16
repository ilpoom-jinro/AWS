ARG MAS_BASE_IMAGE=python:3.12-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

RUN pip install --no-cache-dir "psycopg[binary]==3.2.3"

COPY pods/finops/orchestrator/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
