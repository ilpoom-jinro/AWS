ARG MAS_BASE_IMAGE=financial/mas-base:latest
FROM ${MAS_BASE_IMAGE}

COPY shared/ ./app/
COPY pods/orchestrator/app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
