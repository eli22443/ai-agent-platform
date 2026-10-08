#!/usr/bin/env bash
# Recreate ElastiCache Redis replication group, sync REDIS_URL, scale ECS on.
# Usage: ./infrastructure/aws/start.sh
# Wake can take ~5–15 minutes for Redis.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib.sh"

require_aws
discover_redis_network

if redis_exists; then
  status="$(redis_group_status)"
  case "${status}" in
    available)
      log "Redis ${REDIS_REPLICATION_GROUP_ID} already available; skipping create"
      ;;
    creating|modifying|snapshotting|rebooting*|backing-up)
      log "Redis status=${status}; waiting for available …"
      wait_redis_status available
      ;;
    deleting)
      log "Redis is deleting; waiting until gone, then recreating …"
      wait_redis_status gone
      status="MISSING"
      ;;
    *)
      die "unexpected Redis status=${status}; fix in console or wait"
      ;;
  esac
else
  status="MISSING"
fi

if [[ "${status}" == "MISSING" ]]; then
  log "Creating ElastiCache replication group ${REDIS_REPLICATION_GROUP_ID} (${CACHE_NODE_TYPE})"
  aws_cli elasticache create-replication-group \
    --replication-group-id "${REDIS_REPLICATION_GROUP_ID}" \
    --replication-group-description "ai-agent demo redis" \
    --engine "${REDIS_ENGINE}" \
    --engine-version "${REDIS_ENGINE_VERSION}" \
    --cache-node-type "${CACHE_NODE_TYPE}" \
    --num-cache-clusters "${REDIS_NUM_CACHE_CLUSTERS}" \
    --port "${REDIS_PORT}" \
    --cache-subnet-group-name "${REDIS_SUBNET_GROUP_NAME}" \
    --security-group-ids "${REDIS_SECURITY_GROUP_ID}" \
    --at-rest-encryption-enabled \
    --snapshot-retention-limit "${REDIS_SNAPSHOT_RETENTION}" \
    --query 'ReplicationGroup.Status' \
    --output text >/dev/null
  wait_redis_status available
fi

host="$(redis_endpoint)"
if [[ -z "${host}" || "${host}" == "None" ]]; then
  die "could not read Redis primary endpoint after create"
fi

update_redis_url_secret "${host}"

log "==> start: scaling ECS services to ${DESIRED_COUNT_ON}"
ecs_scale "${ECS_API_SERVICE}" "${DESIRED_COUNT_ON}"
ecs_scale "${ECS_WORKER_SERVICE}" "${DESIRED_COUNT_ON}"

# Secrets are injected at task start; force new tasks if services were already running.
ecs_force_redeploy "${ECS_API_SERVICE}"
ecs_force_redeploy "${ECS_WORKER_SERVICE}"

log "Waiting for API /health (up to ${WAIT_TIMEOUT_SECONDS}s) …"
deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  if curl -fsS --max-time 5 "${HEALTH_URL}" >/dev/null 2>&1; then
    log "Health OK: ${HEALTH_URL}"
    log "==> start: done"
    exit 0
  fi
  sleep "${POLL_INTERVAL_SECONDS}"
done

log "warning: timed out waiting for ${HEALTH_URL}; check ECS tasks / target group"
log "==> start: finished with health still pending"
exit 0
