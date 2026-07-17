#!/bin/sh
set -eu

KUBECONFIG_PATH="${KUBECONFIG:-/tmp/aiops-kubeconfig}"
export KUBECONFIG="${KUBECONFIG_PATH}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"

# Ops EKS는 orchestrator가 실행되는 클러스터다. AWS EKS 토큰 대신 Pod의
# ServiceAccount 토큰을 사용해야 Pod Identity/EKS access entry 상태와 무관하게
# 기존 Kubernetes RBAC로 실행 권한을 검증할 수 있다.
if [ -n "${OPS_KUBE_CONTEXT:-}" ]; then
  : "${KUBERNETES_SERVICE_HOST:?Kubernetes Service host is required}"
  KUBERNETES_SERVICE_PORT="${KUBERNETES_SERVICE_PORT_HTTPS:-${KUBERNETES_SERVICE_PORT:-443}}"
  SERVICE_ACCOUNT_DIR="/var/run/secrets/kubernetes.io/serviceaccount"
  SERVICE_ACCOUNT_TOKEN="${SERVICE_ACCOUNT_DIR}/token"
  SERVICE_ACCOUNT_CA="${SERVICE_ACCOUNT_DIR}/ca.crt"

  if [ ! -r "${SERVICE_ACCOUNT_TOKEN}" ] || [ ! -r "${SERVICE_ACCOUNT_CA}" ]; then
    echo "Ops in-cluster ServiceAccount credentials are unavailable" >&2
    exit 1
  fi

  umask 077
  cat > "${KUBECONFIG_PATH}" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: ${OPS_KUBE_CONTEXT}
    cluster:
      certificate-authority: ${SERVICE_ACCOUNT_CA}
      server: https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}
contexts:
  - name: ${OPS_KUBE_CONTEXT}
    context:
      cluster: ${OPS_KUBE_CONTEXT}
      user: ${OPS_KUBE_CONTEXT}
users:
  - name: ${OPS_KUBE_CONTEXT}
    user:
      tokenFile: ${SERVICE_ACCOUNT_TOKEN}
current-context: ${OPS_KUBE_CONTEXT}
EOF
fi

# Service EKS는 원격 클러스터이므로 Pod Identity로 EKS 인증 토큰을 발급받아
# 별도 kubeconfig context를 추가한다.
if [ -n "${SERVICE_EKS_CLUSTER_NAME:-}" ] && [ -n "${SERVICE_KUBE_CONTEXT:-}" ]; then
  aws eks update-kubeconfig \
    --region "${AWS_REGION}" \
    --name "${SERVICE_EKS_CLUSTER_NAME}" \
    --alias "${SERVICE_KUBE_CONTEXT}" \
    --kubeconfig "${KUBECONFIG_PATH}"
fi

exec "$@"
