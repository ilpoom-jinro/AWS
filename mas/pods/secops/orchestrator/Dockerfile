ARG MAS_BASE_IMAGE=python:3.12-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

RUN pip install --no-cache-dir \
    "boto3" \
    "psycopg[binary]==3.2.3" \
    "pydantic-settings" \
    "temporalio"
    # 주의: FinOps Dockerfile은 temporalio==1.9.0 핀.
    # SecOps는 Pydantic 데이터 컨버터(temporalio.contrib.pydantic)를 쓰므로
    # 해당 기능이 포함된 버전이 필요 → 팀과 버전 정렬 필요(아래 설명)

# FinOps와 달리 SecOps 코드는 contracts/workflows도 import하므로 함께 복사
COPY pods/secops/orchestrator/app ./app
COPY shared ./shared
COPY contracts ./contracts
COPY workflows ./workflows

# 워커 실행 (FastAPI로 감싸려면 FinOps main.py 패턴 참고)
CMD ["python", "-m", "app.worker"]
