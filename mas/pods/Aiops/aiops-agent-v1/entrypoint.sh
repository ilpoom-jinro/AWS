#!/bin/sh
# entrypoint.sh — 기동 시 두 EKS 클러스터의 kubeconfig 생성 후 서버 실행
#
# [v0.2 신규 파일]
# kubectl --context 가 동작하려면 kubeconfig에 두 클러스터의
# 컨텍스트가 등록되어 있어야 한다. Pod Identity가 부여한 IAM Role로
# aws eks update-kubeconfig를 실행해 /tmp/kubeconfig를 생성한다.
set -e

export KUBECONFIG="${KUBECONFIG:-/tmp/kubeconfig}"
export HOME="${HOME:-/tmp}"   # aws cli 캐시 디렉토리 (readonly rootfs 대응)

echo "[entrypoint] kubeconfig 생성: $KUBECONFIG"

if [ -n "$OPS_EKS_CLUSTER_NAME" ]; then
  aws eks update-kubeconfig \
    --region "$AWS_REGION" \
    --name "$OPS_EKS_CLUSTER_NAME" \
    --alias "$OPS_KUBE_CONTEXT" \
    --kubeconfig "$KUBECONFIG"
  echo "[entrypoint] Ops EKS 컨텍스트 등록: $OPS_KUBE_CONTEXT"
else
  echo "[entrypoint] WARN: OPS_EKS_CLUSTER_NAME 미설정 — in-cluster 모드로 동작"
fi

if [ -n "$SERVICE_EKS_CLUSTER_NAME" ]; then
  aws eks update-kubeconfig \
    --region "$AWS_REGION" \
    --name "$SERVICE_EKS_CLUSTER_NAME" \
    --alias "$SERVICE_KUBE_CONTEXT" \
    --kubeconfig "$KUBECONFIG"
  echo "[entrypoint] Service EKS 컨텍스트 등록: $SERVICE_KUBE_CONTEXT"
else
  echo "[entrypoint] WARN: SERVICE_EKS_CLUSTER_NAME 미설정 — Service EKS 감시 불가"
fi

echo "[entrypoint] AIOps Agent 시작 (port=${API_PORT:-8080})"
exec uvicorn aiops.main:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8080}" \
  --workers 1 \
  --log-level info
