#!/usr/bin/env bash
# Deploy the latest ${REPO_BRANCH} to the running instance via SSM:
# git pull → render .env from Secrets Manager → compose up -d --build → health.
# Usage: ./infrastructure/ec2/deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib.sh"

require_aws

id="$(require_instance_id)"
state="$(instance_state "${id}")"
[[ "${state}" == "running" ]] \
  || die "instance ${id} is ${state}; run ./start.sh first (deploy needs a running instance)"

wait_ssm_online "${id}"

remote_script="$(cat <<EOF
source /etc/ai-agent/demo.env
cd "\${APP_DIR}"
git fetch origin "${REPO_BRANCH}"
git checkout "${REPO_BRANCH}"
git pull --ff-only origin "${REPO_BRANCH}"
bash infrastructure/ec2/install-host-files.sh
ai-agent-render-env
ai-agent-compose up -d --build
docker image prune -f
ai-agent-compose ps
EOF
)"

log "Deploying ${REPO_BRANCH} to ${id}"
ssm_run "${id}" "${remote_script}" 1500

wait_health
log "Deploy complete: ${HEALTH_URL%/health}"
