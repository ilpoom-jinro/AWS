#!/usr/bin/env bash
set -euo pipefail

AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-281257473551}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

ANSIBLE_IMAGE="${ANSIBLE_IMAGE:-financial/ansible-codebuild:latest}"

ARGOCD_REPOSITORY="${ARGOCD_REPOSITORY:-financial/argocd}"
ARGOCD_REDIS_REPOSITORY="${ARGOCD_REDIS_REPOSITORY:-financial/argocd-redis}"

ARGOCD_SOURCE_TAG="${ARGOCD_SOURCE_TAG:-}"
ARGOCD_SOURCE_IMAGE="${ARGOCD_SOURCE_IMAGE:-}"
REDIS_SOURCE_IMAGE="${REDIS_SOURCE_IMAGE:-public.ecr.aws/docker/library/redis:7.2.8-alpine}"

if [ -z "${ARGOCD_SOURCE_TAG}" ]; then
  ARGOCD_SOURCE_TAG="$(
    docker run --rm "${ANSIBLE_IMAGE}" \
      sh -lc "awk '/^appVersion:/ { gsub(/\"/, \"\", \$2); print \$2 }' /opt/helm-charts/argo-cd/Chart.yaml"
  )"
fi

if [ -z "${ARGOCD_SOURCE_IMAGE}" ]; then
  ARGOCD_SOURCE_IMAGE="quay.io/argoproj/argocd:${ARGOCD_SOURCE_TAG}"
fi

echo "AWS account: ${AWS_ACCOUNT_ID}"
echo "AWS region: ${AWS_REGION}"
echo "Argo CD source image: ${ARGOCD_SOURCE_IMAGE}"
echo "Redis source image: ${REDIS_SOURCE_IMAGE}"

aws ecr describe-repositories --repository-names "${ARGOCD_REPOSITORY}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${ARGOCD_REPOSITORY}" >/dev/null

aws ecr describe-repositories --repository-names "${ARGOCD_REDIS_REPOSITORY}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${ARGOCD_REDIS_REPOSITORY}" >/dev/null

aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

docker pull "${ARGOCD_SOURCE_IMAGE}"
docker tag "${ARGOCD_SOURCE_IMAGE}" "${ECR_REGISTRY}/${ARGOCD_REPOSITORY}:${ARGOCD_SOURCE_TAG}"
docker tag "${ARGOCD_SOURCE_IMAGE}" "${ECR_REGISTRY}/${ARGOCD_REPOSITORY}:latest"
docker push "${ECR_REGISTRY}/${ARGOCD_REPOSITORY}:${ARGOCD_SOURCE_TAG}"
docker push "${ECR_REGISTRY}/${ARGOCD_REPOSITORY}:latest"

docker pull "${REDIS_SOURCE_IMAGE}"
docker tag "${REDIS_SOURCE_IMAGE}" "${ECR_REGISTRY}/${ARGOCD_REDIS_REPOSITORY}:latest"
docker push "${ECR_REGISTRY}/${ARGOCD_REDIS_REPOSITORY}:latest"

echo "Mirrored images:"
echo "  ${ECR_REGISTRY}/${ARGOCD_REPOSITORY}:${ARGOCD_SOURCE_TAG}"
echo "  ${ECR_REGISTRY}/${ARGOCD_REPOSITORY}:latest"
echo "  ${ECR_REGISTRY}/${ARGOCD_REDIS_REPOSITORY}:latest"
