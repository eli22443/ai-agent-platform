#!/usr/bin/env bash
# Start the demo instance and wait until the public health URL returns 200.
# ai-agent.service brings the compose stack up on boot.
# Usage: ./infrastructure/ec2/start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib.sh"

require_aws

id="$(require_instance_id)"
state="$(instance_state "${id}")"
log "Instance ${id} state=${state}"

case "${state}" in
  running | pending) ;;
  stopping)
    wait_instance_state "${id}" stopped
    aws_cli ec2 start-instances --instance-ids "${id}" >/dev/null
    ;;
  stopped)
    aws_cli ec2 start-instances --instance-ids "${id}" >/dev/null
    ;;
  *) die "unexpected state ${state}" ;;
esac

wait_instance_state "${id}" running
log "Public IP: $(instance_public_ip "${id}")"
wait_health
log "Demo is live: ${HEALTH_URL%/health}"
