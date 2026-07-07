# pinned 2026-07-02, controlled bump via scheduled EOL workflow
ARG MAS_BASE_IMAGE=python:3.12.13-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

RUN pip install --no-cache-dir \
    "slack_bolt==1.28.0" \
    "slack_sdk==3.35.0" \
    "aiohttp==3.14.1" \
    "temporalio==1.27.2" \
    "pydantic==2.10.4"

# contracts 만 필요 — shared/audit 등 다른 모듈 불필요
COPY pods/platform/slack-hitl/bot.py ./bot.py
COPY contracts ./contracts

# SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_CHANNEL_ID,
# TEMPORAL_ADDRESS, HITL_TASK_QUEUE 는 Secret/ConfigMap으로 주입
CMD ["python", "bot.py"]
