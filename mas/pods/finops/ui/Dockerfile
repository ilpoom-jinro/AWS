# pinned 2026-06-30, controlled bump via scheduled EOL workflow (#25)
ARG MAS_BASE_IMAGE=python:3.12.13-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

COPY pods/finops/ui/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
