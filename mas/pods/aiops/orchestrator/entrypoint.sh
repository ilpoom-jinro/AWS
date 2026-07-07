#!/bin/sh
set -eu

KUBECONFIG_PATH="${KUBECONFIG:-/tmp/aiops-kubeconfig}"
export KUBECONFIG="${KUBECONFIG_PATH}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"

if [ -n "${OPS_EKS_CLUSTER_NAME:-}" ] && [ -n "${OPS_KUBE_CONTEXT:-}" ]; then
  aws eks update-kubeconfig \
    --region "${AWS_REGION}" \
    --name "${OPS_EKS_CLUSTER_NAME}" \
    --alias "${OPS_KUBE_CONTEXT}" \
    --kubeconfig "${KUBECONFIG_PATH}"
fi

if [ -n "${SERVICE_EKS_CLUSTER_NAME:-}" ] && [ -n "${SERVICE_KUBE_CONTEXT:-}" ]; then
  aws eks update-kubeconfig \
    --region "${AWS_REGION}" \
    --name "${SERVICE_EKS_CLUSTER_NAME}" \
    --alias "${SERVICE_KUBE_CONTEXT}" \
    --kubeconfig "${KUBECONFIG_PATH}"
fi

exec "$@"
