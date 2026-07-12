# pinned 2026-07-13, controlled bump via scheduled EOL workflow
ARG MAS_BASE_IMAGE=python:3.12.13-slim
FROM ${MAS_BASE_IMAGE}

WORKDIR /app

# SQS 라우터 전환(Socket Mode 제거)에 맞춰 정리:
#   - slack_bolt/slack_sdk 제거 — AsyncApp/AsyncSocketModeHandler/AsyncWebClient를
#     안 쓰게 되며(전부 outbound/inbound SQS로 대체) bot.py에 import 자체가 없음.
#   - aiohttp 제거 — bot.py가 직접 쓰지 않음. slack_bolt/slack_sdk의 비동기 HTTP
#     트랜스포트로 필요했던 전이 의존성이라, 그 둘을 빼면서 같이 정리.
#   - boto3 추가 — outbound(SendMessage)/inbound(Receive/DeleteMessage) SQS 폴링에 필요.
#   - temporalio/pydantic은 계속 사용(Worker/Activity, contracts.models의 pydantic 모델) — 유지.
RUN pip install --no-cache-dir \
    "boto3==1.43.46" \
    "temporalio==1.27.2" \
    "pydantic==2.10.4"

# contracts 만 필요 — shared/audit 등 다른 모듈 불필요
COPY pods/platform/slack-hitl/bot.py ./bot.py
COPY contracts ./contracts

# SLACK_CHANNEL_ID, TEMPORAL_ADDRESS, HITL_TASK_QUEUE,
# OUTBOUND_QUEUE_URL, INBOUND_QUEUE_URL 는 Secret/ConfigMap으로 주입
CMD ["python", "bot.py"]
