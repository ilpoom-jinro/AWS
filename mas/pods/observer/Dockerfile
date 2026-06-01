ARG MAS_BASE_IMAGE=financial/mas-base:latest
FROM ${MAS_BASE_IMAGE}

COPY app/__init__.py ./app/
COPY app/config.py app/schemas.py ./app/
COPY app/agents/__init__.py ./app/agents/
COPY app/agents/observer.py ./app/agents/
COPY app/tools/__init__.py ./app/tools/
COPY app/tools/kubernetes.py app/tools/prometheus.py ./app/tools/
COPY app/entrypoints/__init__.py ./app/entrypoints/
COPY app/entrypoints/observer.py ./app/entrypoints/

CMD ["uvicorn", "app.entrypoints.observer:app", "--host", "0.0.0.0", "--port", "8080"]
