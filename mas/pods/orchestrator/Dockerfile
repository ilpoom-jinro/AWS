ARG MAS_BASE_IMAGE=financial/mas-base:latest
FROM ${MAS_BASE_IMAGE}

COPY app/__init__.py ./app/
COPY app/config.py app/schemas.py ./app/
COPY app/agents/__init__.py ./app/agents/
COPY app/agents/orchestrator.py ./app/agents/
COPY app/entrypoints/__init__.py ./app/entrypoints/
COPY app/entrypoints/orchestrator.py ./app/entrypoints/

CMD ["uvicorn", "app.entrypoints.orchestrator:app", "--host", "0.0.0.0", "--port", "8080"]
