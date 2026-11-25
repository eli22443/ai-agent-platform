#!/usr/bin/env bash
# Stop the demo instance (compose is brought down by ai-agent.service).
# Note: in-flight ARQ jobs are lost on stop.
# Usage: ./infrastructure/ec2/stop.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib.sh"

require_aws

id="$(require_instance_id)"
state="$(instance_state "${id}")"
log "Instance ${id} state=${state}"

case "${state}" in
  stopped) log "Already stopped"; exit 0 ;;
  stopping) ;;
  running | pending) aws_cli ec2 stop-instances --instance-ids "${id}" >/dev/null ;;
  *) die "unexpected state ${state}" ;;
esac

wait_instance_state "${id}" stopped
log "Stopped. While stopped you pay only for EBS + the secret."
