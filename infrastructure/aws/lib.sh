#!/usr/bin/env bash
# Shared helpers for infrastructure/aws schedule scripts.
# Redis target: ElastiCache replication group (e.g. ai-agent-redis → node ai-agent-redis-001).
# shellcheck disable=SC2034

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config.env"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "error: missing ${CONFIG_FILE}" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${CONFIG_FILE}"

# Back-compat if an older config only had REDIS_CLUSTER_ID
: "${REDIS_REPLICATION_GROUP_ID:=${REDIS_CLUSTER_ID:-}}"

: "${AWS_REGION:?}"
: "${ECS_CLUSTER:?}"
: "${ECS_API_SERVICE:?}"
: "${ECS_WORKER_SERVICE:?}"
: "${DESIRED_COUNT_ON:?}"
: "${REDIS_REPLICATION_GROUP_ID:?}"
: "${CACHE_NODE_TYPE:?}"
: "${REDIS_ENGINE:?}"
: "${REDIS_ENGINE_VERSION:?}"
: "${REDIS_PORT:?}"
: "${REDIS_SNAPSHOT_RETENTION:?}"
: "${REDIS_NUM_CACHE_CLUSTERS:?}"
: "${REDIS_SECURITY_GROUP_NAME:?}"
: "${SECRET_ID:?}"
: "${HEALTH_URL:?}"
: "${WAIT_TIMEOUT_SECONDS:?}"
: "${POLL_INTERVAL_SECONDS:?}"

aws_cli() {
  aws --region "${AWS_REGION}" "$@"
}

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

die() {
  log "error: $*"
  exit 1
}

require_aws() {
  command -v aws >/dev/null 2>&1 || die "aws CLI not found"
  command -v python3 >/dev/null 2>&1 || die "python3 not found (needed to merge Secrets Manager JSON)"
  aws_cli sts get-caller-identity --query Account --output text >/dev/null \
    || die "AWS credentials unavailable; run aws login / configure"
}

ecs_scale() {
  local service="$1"
  local count="$2"
  log "Scaling ECS service ${service} → desired=${count}"
  aws_cli ecs update-service \
    --cluster "${ECS_CLUSTER}" \
    --service "${service}" \
    --desired-count "${count}" \
    --query 'service.{name:serviceName,desired:desiredCount,running:runningCount}' \
    --output table >/dev/null
}

ecs_force_redeploy() {
  local service="$1"
  log "Force-redeploying ECS service ${service}"
  aws_cli ecs update-service \
    --cluster "${ECS_CLUSTER}" \
    --service "${service}" \
    --force-new-deployment \
    --query 'service.serviceName' \
    --output text >/dev/null
}

ecs_service_counts() {
  local service="$1"
  aws_cli ecs describe-services \
    --cluster "${ECS_CLUSTER}" \
    --services "${service}" \
    --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount,status:status}' \
    --output json
}

wait_ecs_running_zero() {
  local service="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  log "Waiting for ${service} runningCount=0 …"
  while (( SECONDS < deadline )); do
    local running
    running="$(aws_cli ecs describe-services \
      --cluster "${ECS_CLUSTER}" \
      --services "${service}" \
      --query 'services[0].runningCount' \
      --output text)"
    if [[ "${running}" == "0" || "${running}" == "None" ]]; then
      log "${service}: runningCount=0"
      return 0
    fi
    log "${service}: runningCount=${running}; sleeping ${POLL_INTERVAL_SECONDS}s"
    sleep "${POLL_INTERVAL_SECONDS}"
  done
  die "timed out waiting for ${service} to reach runningCount=0"
}

redis_status() {
  aws_cli elasticache describe-replication-groups \
    --replication-group-id "${REDIS_REPLICATION_GROUP_ID}" \
    --query 'ReplicationGroups[0].{Status:Status,Endpoint:NodeGroups[0].PrimaryEndpoint.Address,Port:NodeGroups[0].PrimaryEndpoint.Port,Members:MemberClusters,NodeType:CacheNodeType}' \
    --output json 2>/dev/null || echo "null"
}

redis_exists() {
  local status
  status="$(aws_cli elasticache describe-replication-groups \
    --replication-group-id "${REDIS_REPLICATION_GROUP_ID}" \
    --query 'ReplicationGroups[0].Status' \
    --output text 2>/dev/null || true)"
  if [[ -z "${status}" || "${status}" == "None" ]]; then
    return 1
  fi
  return 0
}

redis_group_status() {
  aws_cli elasticache describe-replication-groups \
    --replication-group-id "${REDIS_REPLICATION_GROUP_ID}" \
    --query 'ReplicationGroups[0].Status' \
    --output text 2>/dev/null || echo "MISSING"
}

redis_endpoint() {
  aws_cli elasticache describe-replication-groups \
    --replication-group-id "${REDIS_REPLICATION_GROUP_ID}" \
    --query 'ReplicationGroups[0].NodeGroups[0].PrimaryEndpoint.Address' \
    --output text
}

discover_redis_network() {
  if [[ -n "${REDIS_SUBNET_GROUP_NAME:-}" && -n "${REDIS_SECURITY_GROUP_ID:-}" ]]; then
    log "Using Redis subnet group=${REDIS_SUBNET_GROUP_NAME} sg=${REDIS_SECURITY_GROUP_ID}"
    return 0
  fi

  if redis_exists; then
    local member
    member="$(aws_cli elasticache describe-replication-groups \
      --replication-group-id "${REDIS_REPLICATION_GROUP_ID}" \
      --query 'ReplicationGroups[0].MemberClusters[0]' \
      --output text)"
    if [[ -n "${member}" && "${member}" != "None" ]]; then
      local live
      live="$(aws_cli elasticache describe-cache-clusters \
        --cache-cluster-id "${member}" \
        --query 'CacheClusters[0].{sg:SecurityGroups[0].SecurityGroupId,subnet:CacheSubnetGroupName}' \
        --output json)"
      if [[ -z "${REDIS_SECURITY_GROUP_ID:-}" ]]; then
        REDIS_SECURITY_GROUP_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["sg"] or "")' <<<"${live}")"
      fi
      if [[ -z "${REDIS_SUBNET_GROUP_NAME:-}" ]]; then
        REDIS_SUBNET_GROUP_NAME="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["subnet"] or "")' <<<"${live}")"
      fi
    fi
  fi

  if [[ -z "${REDIS_SECURITY_GROUP_ID:-}" ]]; then
    REDIS_SECURITY_GROUP_ID="$(aws_cli ec2 describe-security-groups \
      --filters "Name=group-name,Values=${REDIS_SECURITY_GROUP_NAME}" \
      --query 'SecurityGroups[0].GroupId' \
      --output text)"
    if [[ -z "${REDIS_SECURITY_GROUP_ID}" || "${REDIS_SECURITY_GROUP_ID}" == "None" ]]; then
      die "could not find security group named ${REDIS_SECURITY_GROUP_NAME}"
    fi
  fi

  if [[ -z "${REDIS_SUBNET_GROUP_NAME:-}" ]]; then
    REDIS_SUBNET_GROUP_NAME="$(aws_cli elasticache describe-cache-subnet-groups \
      --query 'CacheSubnetGroups[?contains(CacheSubnetGroupName, `redis`) || contains(CacheSubnetGroupName, `ai-agent`)].CacheSubnetGroupName | [0]' \
      --output text)"
    if [[ -z "${REDIS_SUBNET_GROUP_NAME}" || "${REDIS_SUBNET_GROUP_NAME}" == "None" ]]; then
      REDIS_SUBNET_GROUP_NAME="$(aws_cli elasticache describe-cache-subnet-groups \
        --query 'CacheSubnetGroups[0].CacheSubnetGroupName' \
        --output text)"
    fi
    if [[ -z "${REDIS_SUBNET_GROUP_NAME}" || "${REDIS_SUBNET_GROUP_NAME}" == "None" ]]; then
      die "could not discover ElastiCache subnet group; set REDIS_SUBNET_GROUP_NAME in config.env"
    fi
  fi

  log "Using Redis subnet group=${REDIS_SUBNET_GROUP_NAME} sg=${REDIS_SECURITY_GROUP_ID}"
}

wait_redis_status() {
  local want="$1" # available | gone
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  log "Waiting for Redis replication group ${REDIS_REPLICATION_GROUP_ID} → ${want} …"
  while (( SECONDS < deadline )); do
    local status
    status="$(redis_group_status)"
    if [[ "${want}" == "gone" ]]; then
      if [[ "${status}" == "MISSING" || "${status}" == "None" ]]; then
        log "Redis replication group deleted"
        return 0
      fi
    else
      if [[ "${status}" == "${want}" ]]; then
        log "Redis status=${status}"
        return 0
      fi
      if [[ "${status}" == "MISSING" || "${status}" == "None" ]]; then
        die "Redis replication group missing while waiting for ${want}"
      fi
    fi
    log "Redis status=${status}; sleeping ${POLL_INTERVAL_SECONDS}s"
    sleep "${POLL_INTERVAL_SECONDS}"
  done
  die "timed out waiting for Redis ${want}"
}

update_redis_url_secret() {
  local host="$1"
  local url="redis://${host}:${REDIS_PORT}/0"
  log "Updating Secrets Manager ${SECRET_ID} REDIS_URL → ${url}"

  local current
  current="$(aws_cli secretsmanager get-secret-value \
    --secret-id "${SECRET_ID}" \
    --query SecretString \
    --output text)"

  local merged
  merged="$(REDIS_URL_VALUE="${url}" python3 -c '
import json, os, sys
data = json.loads(sys.stdin.read())
if not isinstance(data, dict):
    raise SystemExit("secret is not a JSON object")
data["REDIS_URL"] = os.environ["REDIS_URL_VALUE"]
print(json.dumps(data))
' <<<"${current}")"

  aws_cli secretsmanager put-secret-value \
    --secret-id "${SECRET_ID}" \
    --secret-string "${merged}" \
    --query 'VersionId' \
    --output text >/dev/null

  log "Secret REDIS_URL updated"
}
