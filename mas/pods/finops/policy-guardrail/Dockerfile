ARG MAS_BASE_IMAGE=python:3.12-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

COPY pods/finops/agents/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
