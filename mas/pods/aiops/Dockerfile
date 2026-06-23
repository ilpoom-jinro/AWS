# ── Stage 1: 빌드 ────────────────────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# ── Stage 2: 런타임 ──────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# awscli v2 + kubectl (읽기 전용 수집용)
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl unzip ca-certificates \
 && curl -Lo /tmp/awscliv2.zip "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
 && unzip -q /tmp/awscliv2.zip -d /tmp && /tmp/aws/install \
 && curl -Lo /usr/local/bin/kubectl "https://dl.k8s.io/release/v1.32.0/bin/linux/amd64/kubectl" \
 && chmod +x /usr/local/bin/kubectl \
 && apt-get purge -y curl unzip && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ ./src/
COPY entrypoint.sh /app/entrypoint.sh

ENV PYTHONPATH=/app/src
RUN useradd -r -u 1001 aiops && chmod +x /app/entrypoint.sh
USER aiops

# Worker는 HTTP 포트 없음 (Temporal long-poll). HEALTHCHECK 제거.
ENTRYPOINT ["/app/entrypoint.sh"]
