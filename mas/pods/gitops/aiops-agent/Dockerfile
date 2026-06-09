# ── Stage 1: 빌드 ────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# 의존성 설치 (소스 복사 전 — 레이어 캐시 활용)
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

# ── Stage 2: 런타임 ──────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# kubectl 설치
ARG KUBECTL_VERSION=v1.35.0
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -Lo /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
 && chmod +x /usr/local/bin/kubectl \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# helm 설치
ARG HELM_VERSION=v3.17.3
RUN apt-get update && apt-get install -y --no-install-recommends curl tar \
 && curl -fsSLo /tmp/helm.tar.gz \
      "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" \
 && tar -xzf /tmp/helm.tar.gz -C /tmp \
 && mv /tmp/linux-amd64/helm /usr/local/bin/helm \
 && chmod +x /usr/local/bin/helm \
 && apt-get purge -y curl tar \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/*

# 빌드 스테이지에서 설치된 패키지 복사
COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 소스 복사
COPY src/ ./src/

# 비루트 사용자 실행
RUN useradd -r -u 1001 aiops
USER aiops

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -sf http://localhost:8080/healthz || exit 1

CMD ["uvicorn", "aiops.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "1", "--log-level", "info"]
