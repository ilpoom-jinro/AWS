# pinned 2026-06-30, controlled bump via scheduled EOL workflow (#25)
FROM python:3.12.13-slim

# spaCy 런타임 최소 빌드 의존성
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 스캐너 코드 베이크인 (CodeBuild는 NO_SOURCE라 코드가 이미지에 있어야 함)
COPY kr_recognizers.py scan.py ./
# CodeBuild는 buildspec 명령으로 실행하므로 ENTRYPOINT는 생략(로컬 테스트 시 python scan.py)
