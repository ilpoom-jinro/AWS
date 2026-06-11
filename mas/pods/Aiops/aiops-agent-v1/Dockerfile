# ── Stage 1: Python 의존성 빌드 ─────────────────────────────────
# [v0.2 수정사항]
# - 기존: builder에 src/ 미복사 상태로 pip install . → 패키지 없음 오류로 빌드 실패
# - 기존: build-backend 오타(setuptools.backends.legacy:build)로 설치 자체 불가
# - 기존: curl을 purge한 뒤 HEALTHCHECK에서 curl 사용 → 헬스체크 항상 실패
# - 기존: aws CLI 부재 → kubectl의 EKS 토큰 발급(exec aws eks get-token) 불가
# - 수정: src 복사 후 설치 / awscli v2 설치 / HEALTHCHECK 제거(K8s probe 사용)
#         / entrypoint.sh에서 kubeconfig 생성
FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

# ── Stage 2: 런타임 ──────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

ARG KUBECTL_VERSION=v1.31.4
ARG HELM_VERSION=v3.16.3

# 시스템 의존성 + kubectl + helm + awscli v2
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates unzip \
 && curl -fsSLo /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
 && chmod +x /usr/local/bin/kubectl \
 && curl -fsSLo /tmp/helm.tar.gz \
      "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" \
 && tar -xzf /tmp/helm.tar.gz -C /tmp \
 && mv /tmp/linux-amd64/helm /usr/local/bin/helm \
 && chmod +x /usr/local/bin/helm \
 && curl -fsSLo /tmp/awscliv2.zip \
      "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
 && unzip -q /tmp/awscliv2.zip -d /tmp \
 && /tmp/aws/install \
 && rm -rf /tmp/helm.tar.gz /tmp/linux-amd64 /tmp/awscliv2.zip /tmp/aws \
 && apt-get purge -y unzip \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# 빌드 스테이지의 site-packages + 콘솔 스크립트(uvicorn) 복사
COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# 비루트 사용자
RUN useradd -r -u 1001 -d /tmp aiops
USER aiops

ENV HOME=/tmp \
    KUBECONFIG=/tmp/kubeconfig

EXPOSE 8080

# HEALTHCHECK 제거: K8s liveness/readiness probe가 /healthz를 직접 검사
ENTRYPOINT ["/app/entrypoint.sh"]
