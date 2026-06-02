ARG MAS_BASE_IMAGE=financial/mas-base:latest
FROM ${MAS_BASE_IMAGE}

COPY app/__init__.py ./app/
COPY app/config.py ./app/
COPY app/entrypoints/__init__.py ./app/entrypoints/
COPY app/entrypoints/ui.py ./app/entrypoints/

CMD ["uvicorn", "app.entrypoints.ui:app", "--host", "0.0.0.0", "--port", "8080"]
