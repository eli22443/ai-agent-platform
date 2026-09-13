#!/bin/bash

# Replace REGION and ACCOUNT (from aws sts get-caller-identity)
REGION=eu-north-1
ACCOUNT=099357569747
REPO="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/ai-agent-platform"

aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

docker build -t ai-agent-platform:latest ./backend
docker tag ai-agent-platform:latest "${REPO}:latest"
docker push "${REPO}:latest"