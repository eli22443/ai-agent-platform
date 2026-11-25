#!/usr/bin/env bash
# Shared helpers for infrastructure/ec2 scripts (run from your laptop).
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

: "${AWS_REGION:?}"
: "${INSTANCE_NAME:?}"
: "${INSTANCE_TYPE:?}"
: "${ROOT_VOLUME_GB:?}"
: "${AMI_SSM_PARAMETER:?}"
: "${VPC_NAME:?}"
: "${SUBNET_NAME:?}"
: "${SECURITY_GROUP_NAME:?}"
: "${ROLE_NAME:?}"
: "${INSTANCE_PROFILE_NAME:?}"
: "${SECRETS_ARN_PATTERN:?}"
: "${SECRET_ID:?}"
: "${DEMO_HOSTNAME:?}"
: "${HEALTH_URL:?}"
: "${REPO_URL:?}"
: "${REPO_BRANCH:?}"
: "${APP_DIR:?}"
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
  command -v python3 >/dev/null 2>&1 || die "python3 not found (needed to build SSM parameters)"
  command -v curl >/dev/null 2>&1 || die "curl not found"
  aws_cli sts get-caller-identity --query Account --output text >/dev/null \
    || die "AWS credentials unavailable; run aws login / configure"
}

# Prints the instance ID for the demo host, or nothing if none exists
# (terminated instances are ignored).
instance_id() {
  local id
  id="$(aws_cli ec2 describe-instances \
    --filters "Name=tag:Name,Values=${INSTANCE_NAME}" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId | [0]' \
    --output text)"
  if [[ -z "${id}" || "${id}" == "None" ]]; then
    return 0
  fi
  printf '%s\n' "${id}"
}

require_instance_id() {
  local id
  id="$(instance_id)"
  [[ -n "${id}" ]] || die "no instance tagged Name=${INSTANCE_NAME}; run ./provision.sh first"
  printf '%s\n' "${id}"
}

instance_state() {
  aws_cli ec2 describe-instances \
    --instance-ids "$1" \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text
}

instance_public_ip() {
  local ip
  ip="$(aws_cli ec2 describe-instances \
    --instance-ids "$1" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)"
  if [[ "${ip}" == "None" ]]; then
    ip=""
  fi
  printf '%s\n' "${ip}"
}

wait_instance_state() {
  local id="$1"
  local want="$2" # running | stopped
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  log "Waiting for ${id} → ${want} …"
  while (( SECONDS < deadline )); do
    local state
    state="$(instance_state "${id}")"
    if [[ "${state}" == "${want}" ]]; then
      log "${id}: ${state}"
      return 0
    fi
    if [[ "${state}" == "terminated" || "${state}" == "shutting-down" ]]; then
      die "${id} is ${state} while waiting for ${want}"
    fi
    log "${id}: ${state}; sleeping ${POLL_INTERVAL_SECONDS}s"
    sleep "${POLL_INTERVAL_SECONDS}"
  done
  die "timed out waiting for ${id} to reach ${want}"
}

wait_health() {
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  log "Waiting for ${HEALTH_URL} …"
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 5 "${HEALTH_URL}" >/dev/null 2>&1; then
      log "Health OK: ${HEALTH_URL}"
      return 0
    fi
    sleep "${POLL_INTERVAL_SECONDS}"
  done
  die "timed out waiting for ${HEALTH_URL}"
}

wait_ssm_online() {
  local id="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  log "Waiting for SSM agent on ${id} …"
  while (( SECONDS < deadline )); do
    local ping
    ping="$(aws_cli ssm describe-instance-information \
      --filters "Key=InstanceIds,Values=${id}" \
      --query 'InstanceInformationList[0].PingStatus' \
      --output text 2>/dev/null || true)"
    if [[ "${ping}" == "Online" ]]; then
      log "SSM agent online"
      return 0
    fi
    sleep "${POLL_INTERVAL_SECONDS}"
  done
  die "timed out waiting for SSM agent on ${id}"
}

# ssm_run INSTANCE_ID SCRIPT [TIMEOUT_SECONDS]
# Runs SCRIPT (bash source) via AWS-RunShellScript, streams its output, and
# fails if the command does not finish with Status=Success.
ssm_run() {
  local id="$1"
  local script="$2"
  local timeout="${3:-900}"

  local params
  params="$(SSM_SCRIPT="bash -s <<'__SSM_EOF__'
set -euo pipefail
${script}
__SSM_EOF__" SSM_TIMEOUT="${timeout}" python3 -c '
import json, os
print(json.dumps({
    "commands": [os.environ["SSM_SCRIPT"]],
    "executionTimeout": [os.environ["SSM_TIMEOUT"]],
}))
')"

  local cmd_id
  cmd_id="$(aws_cli ssm send-command \
    --instance-ids "${id}" \
    --document-name AWS-RunShellScript \
    --comment "ai-agent-demo" \
    --parameters "${params}" \
    --query 'Command.CommandId' \
    --output text)"
  log "SSM command ${cmd_id} sent"

  local deadline=$((SECONDS + timeout + 60))
  local status=""
  while (( SECONDS < deadline )); do
    status="$(aws_cli ssm get-command-invocation \
      --command-id "${cmd_id}" \
      --instance-id "${id}" \
      --query 'Status' \
      --output text 2>/dev/null || true)"
    case "${status}" in
      Success | Failed | Cancelled | TimedOut | Cancelling) break ;;
    esac
    sleep 5
  done

  aws_cli ssm get-command-invocation \
    --command-id "${cmd_id}" \
    --instance-id "${id}" \
    --query 'StandardOutputContent' \
    --output text || true
  local stderr_out
  stderr_out="$(aws_cli ssm get-command-invocation \
    --command-id "${cmd_id}" \
    --instance-id "${id}" \
    --query 'StandardErrorContent' \
    --output text 2>/dev/null || true)"
  if [[ -n "${stderr_out}" && "${stderr_out}" != "None" ]]; then
    printf '%s\n' "${stderr_out}" >&2
  fi

  [[ "${status}" == "Success" ]] || die "SSM command ${cmd_id} finished with status=${status:-unknown}"
}
