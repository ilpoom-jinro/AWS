#!/usr/bin/env bash
set -euo pipefail

AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-218549830271}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
PROMETHEUS_VERSION="${PROMETHEUS_VERSION:-v3.7.3}"
ECR_REPOSITORY="${ECR_REPOSITORY:-financial/prometheus}"

SOURCE_IMAGE="quay.io/prometheus/prometheus:${PROMETHEUS_VERSION}"
TARGET_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:${PROMETHEUS_VERSION}"

aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

docker pull "${SOURCE_IMAGE}"
docker tag "${SOURCE_IMAGE}" "${TARGET_IMAGE}"
docker push "${TARGET_IMAGE}"
