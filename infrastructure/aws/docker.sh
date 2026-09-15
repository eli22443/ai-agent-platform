#!/usr/bin/env bash
# Build the app image, push to ECR, and force-redeploy API + worker on ECS (14a).
# Usage (from anywhere): ./infrastructure/aws/docker.sh
# Requires: aws CLI, docker, credentials for account that owns ai-agent-platform ECR.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

REGION="${REGION:-eu-north-1}"
CLUSTER="${CLUSTER:-ai-agent-cluster}"
API_SERVICE="${API_SERVICE:-ai-agent-api-service-2sdqusn9}"
WORKER_SERVICE="${WORKER_SERVICE:-ai-agent-worker-service}"
IMAGE_NAME="${IMAGE_NAME:-ai-agent-platform}"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REPO="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${IMAGE_NAME}"

echo "==> Logging in to ECR (${REGION})"
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin \
      "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

echo "==> Building ${IMAGE_NAME}:latest from ${ROOT_DIR}/backend"
docker build -t "${IMAGE_NAME}:latest" "${ROOT_DIR}/backend"
docker tag "${IMAGE_NAME}:latest" "${REPO}:latest"

echo "==> Pushing ${REPO}:latest"
docker push "${REPO}:latest"

echo "==> Force-redeploying ECS services"
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "${API_SERVICE}" \
  --force-new-deployment \
  --region "${REGION}" \
  --query 'service.serviceName' \
  --output text

aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "${WORKER_SERVICE}" \
  --force-new-deployment \
  --region "${REGION}" \
  --query 'service.serviceName' \
  --output text

echo "==> Done. New tasks will pull ${REPO}:latest shortly."
echo "    Verify: curl http://<ALB-DNS>/health"
echo "    Logs:   /ecs/ai-agent-api  /ecs/ai-agent-worker"
