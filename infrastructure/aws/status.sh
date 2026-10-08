#!/usr/bin/env bash
# Print ECS desired/running counts, Redis status/endpoint, and /health.
# Usage: ./infrastructure/aws/status.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib.sh"

require_aws

echo "Region:  ${AWS_REGION}"
echo "Cluster: ${ECS_CLUSTER}"
echo

echo "=== ECS ==="
for svc in "${ECS_API_SERVICE}" "${ECS_WORKER_SERVICE}"; do
  echo "--- ${svc} ---"
  ecs_service_counts "${svc}" | python3 -m json.tool
done

echo
echo "=== Redis replication group (${REDIS_REPLICATION_GROUP_ID}) ==="
redis_json="$(redis_status)"
if [[ "${redis_json}" == "null" ]]; then
  echo "absent"
else
  python3 -m json.tool <<<"${redis_json}"
fi

echo
echo "=== Health ==="
if curl -fsS --max-time 5 "${HEALTH_URL}"; then
  echo
else
  echo "(unreachable or unhealthy: ${HEALTH_URL})"
fi
