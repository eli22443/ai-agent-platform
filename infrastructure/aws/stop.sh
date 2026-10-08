#!/usr/bin/env bash
# Scale ECS API + worker to 0, then delete ElastiCache Redis replication group.
# Usage: ./infrastructure/aws/stop.sh
# Leaves ALB / VPC / Secrets Manager running.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib.sh"

require_aws

log "==> stop: scaling ECS services to 0"
ecs_scale "${ECS_API_SERVICE}" 0
ecs_scale "${ECS_WORKER_SERVICE}" 0
wait_ecs_running_zero "${ECS_API_SERVICE}"
wait_ecs_running_zero "${ECS_WORKER_SERVICE}"

if ! redis_exists; then
  log "Redis ${REDIS_REPLICATION_GROUP_ID} already absent; nothing to delete"
  log "==> stop: done"
  exit 0
fi

status="$(redis_group_status)"

if [[ "${status}" == "deleting" ]]; then
  log "Redis already deleting; waiting …"
  wait_redis_status gone
  log "==> stop: done"
  exit 0
fi

log "Deleting ElastiCache replication group ${REDIS_REPLICATION_GROUP_ID} (status=${status})"
aws_cli elasticache delete-replication-group \
  --replication-group-id "${REDIS_REPLICATION_GROUP_ID}" \
  --no-retain-primary-cluster \
  --query 'ReplicationGroup.Status' \
  --output text >/dev/null

wait_redis_status gone
log "==> stop: done (ECS=0, Redis deleted; ALB still running)"
