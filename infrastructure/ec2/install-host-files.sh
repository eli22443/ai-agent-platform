#!/usr/bin/env bash
# Runs ON the instance (user-data and deploy.sh). Copies the helper scripts and
# systemd unit from the checked-out repo into place, so `git pull` + this script
# is enough to roll out changes to them.

set -euo pipefail

# shellcheck source=/dev/null
source /etc/ai-agent/demo.env

: "${APP_DIR:?}"
src="${APP_DIR}/infrastructure/ec2"

install -m 0755 "${src}/render-env.sh" /usr/local/bin/ai-agent-render-env
install -m 0755 "${src}/compose.sh" /usr/local/bin/ai-agent-compose
install -m 0644 "${src}/ai-agent.service" /etc/systemd/system/ai-agent.service
systemctl daemon-reload
systemctl enable ai-agent.service
echo "host files installed"
