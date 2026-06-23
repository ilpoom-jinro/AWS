#!/usr/bin/env sh
set -e

# [MAS] FastAPI/uvicorn 대신 Temporal Worker 실행.
# 멀티 클러스터 kubeconfig 생성 (읽기 전용 수집용).
export HOME=/tmp
export KUBECONFIG=/tmp/kubeconfig

if [ -n "$OPS_EKS_CLUSTER_NAME" ]; then
  aws eks update-kubeconfig \
    --name "$OPS_EKS_CLUSTER_NAME" \
    --alias "$OPS_KUBE_CONTEXT" \
    --kubeconfig /tmp/kubeconfig
fi

if [ -n "$SERVICE_EKS_CLUSTER_NAME" ]; then
  aws eks update-kubeconfig \
    --name "$SERVICE_EKS_CLUSTER_NAME" \
    --alias "$SERVICE_KUBE_CONTEXT" \
    --kubeconfig /tmp/kubeconfig
fi

exec python -m aiops.worker
