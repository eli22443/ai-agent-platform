#!/usr/bin/env bash
# Runs ON the instance. Wraps docker compose with the EC2 override files.
# Installed as /usr/local/bin/ai-agent-compose by install-host-files.sh.
# Usage: ai-agent-compose up -d --build | down | logs -f api | ps

set -euo pipefail

# shellcheck source=/dev/null
source /etc/ai-agent/demo.env

: "${APP_DIR:?}"

cd "${APP_DIR}"
exec docker compose \
  -f docker-compose.yml \
  -f docker-compose.ec2.yml \
  --env-file backend/.env \
  "$@"
