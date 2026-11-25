#!/usr/bin/env bash
# Print instance state, public IP, and the public /health result.
# Usage: ./infrastructure/ec2/status.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib.sh"

require_aws

echo "Region:   ${AWS_REGION}"
echo "Name:     ${INSTANCE_NAME} (${INSTANCE_TYPE})"
echo "Hostname: ${DEMO_HOSTNAME}"
echo

id="$(instance_id)"
if [[ -z "${id}" ]]; then
  echo "=== Instance ==="
  echo "absent (run ./provision.sh)"
  exit 0
fi

state="$(instance_state "${id}")"
echo "=== Instance ==="
echo "id:    ${id}"
echo "state: ${state}"
echo "ip:    $(instance_public_ip "${id}")"

echo
echo "=== Health ==="
if curl -fsS --max-time 5 "${HEALTH_URL}"; then
  echo
else
  echo "(unreachable or unhealthy: ${HEALTH_URL})"
fi
