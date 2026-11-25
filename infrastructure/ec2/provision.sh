#!/usr/bin/env bash
# One-time setup: security group, IAM role/profile, and the EC2 instance.
# Idempotent for SG/IAM; refuses to create a second instance.
# Usage: ./infrastructure/ec2/provision.sh [--no-wait]
#
# Prereq: infrastructure/ec2/*, docker-compose.ec2.yml must be pushed to
# ${REPO_BRANCH} (the instance clones the repo on first boot), and the secret
# ${SECRET_ID} must contain CLOUDFLARE_TUNNEL_TOKEN.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib.sh"

WAIT=1
for arg in "$@"; do
  case "${arg}" in
    --no-wait) WAIT=0 ;;
    *) die "unknown argument: ${arg}" ;;
  esac
done

require_aws

existing="$(instance_id)"
[[ -z "${existing}" ]] || die "instance ${existing} already tagged Name=${INSTANCE_NAME}; use start.sh/deploy.sh"

# --- Secret sanity ----------------------------------------------------------
log "Checking secret ${SECRET_ID} has CLOUDFLARE_TUNNEL_TOKEN"
has_token="$(aws_cli secretsmanager get-secret-value \
  --secret-id "${SECRET_ID}" \
  --query SecretString --output text \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("yes" if d.get("CLOUDFLARE_TUNNEL_TOKEN") else "no")')"
[[ "${has_token}" == "yes" ]] || die "secret ${SECRET_ID} is missing CLOUDFLARE_TUNNEL_TOKEN"

# --- Network lookup ---------------------------------------------------------
vpc_id="$(aws_cli ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=${VPC_NAME}" \
  --query 'Vpcs[0].VpcId' --output text)"
[[ -n "${vpc_id}" && "${vpc_id}" != "None" ]] || die "VPC ${VPC_NAME} not found"

subnet_id="$(aws_cli ec2 describe-subnets \
  --filters "Name=tag:Name,Values=${SUBNET_NAME}" "Name=vpc-id,Values=${vpc_id}" \
  --query 'Subnets[0].SubnetId' --output text)"
[[ -n "${subnet_id}" && "${subnet_id}" != "None" ]] || die "subnet ${SUBNET_NAME} not found in ${vpc_id}"
log "Using vpc=${vpc_id} subnet=${subnet_id}"

# --- Security group (no inbound rules, all outbound) ------------------------
sg_id="$(aws_cli ec2 describe-security-groups \
  --filters "Name=group-name,Values=${SECURITY_GROUP_NAME}" "Name=vpc-id,Values=${vpc_id}" \
  --query 'SecurityGroups[0].GroupId' --output text)"
if [[ -z "${sg_id}" || "${sg_id}" == "None" ]]; then
  log "Creating security group ${SECURITY_GROUP_NAME}"
  sg_id="$(aws_cli ec2 create-security-group \
    --group-name "${SECURITY_GROUP_NAME}" \
    --description "ai-agent demo host: no inbound, SSM + Cloudflare Tunnel only" \
    --vpc-id "${vpc_id}" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=${SECURITY_GROUP_NAME}}]" \
    --query 'GroupId' --output text)"
else
  log "Security group ${SECURITY_GROUP_NAME} exists (${sg_id})"
fi

# --- IAM role + instance profile --------------------------------------------
trust_policy='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
secrets_policy="$(SECRETS_ARN_PATTERN="${SECRETS_ARN_PATTERN}" python3 -c '
import json, os
print(json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": "secretsmanager:GetSecretValue",
        "Resource": os.environ["SECRETS_ARN_PATTERN"],
    }],
}))
')"

if ! aws_cli iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  log "Creating IAM role ${ROLE_NAME}"
  aws_cli iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "${trust_policy}" \
    --description "ai-agent demo EC2: SSM + read app secrets" >/dev/null
else
  log "IAM role ${ROLE_NAME} exists"
fi
aws_cli iam attach-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws_cli iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name read-app-secrets \
  --policy-document "${secrets_policy}"

if ! aws_cli iam get-instance-profile --instance-profile-name "${INSTANCE_PROFILE_NAME}" >/dev/null 2>&1; then
  log "Creating instance profile ${INSTANCE_PROFILE_NAME}"
  aws_cli iam create-instance-profile --instance-profile-name "${INSTANCE_PROFILE_NAME}" >/dev/null
  aws_cli iam wait instance-profile-exists --instance-profile-name "${INSTANCE_PROFILE_NAME}"
fi
attached="$(aws_cli iam get-instance-profile \
  --instance-profile-name "${INSTANCE_PROFILE_NAME}" \
  --query "InstanceProfile.Roles[?RoleName=='${ROLE_NAME}'] | length(@)" --output text)"
if [[ "${attached}" == "0" ]]; then
  aws_cli iam add-role-to-instance-profile \
    --instance-profile-name "${INSTANCE_PROFILE_NAME}" \
    --role-name "${ROLE_NAME}"
  log "Waiting for IAM propagation"
  sleep 15
fi

# --- AMI + user-data --------------------------------------------------------
ami_id="$(aws_cli ssm get-parameter \
  --name "${AMI_SSM_PARAMETER}" \
  --query 'Parameter.Value' --output text)"
log "AMI ${ami_id}"

user_data_file="$(mktemp)"
trap 'rm -f "${user_data_file}"' EXIT
{
  echo '#!/bin/bash'
  printf 'export AWS_REGION=%q\n' "${AWS_REGION}"
  printf 'export SECRET_ID=%q\n' "${SECRET_ID}"
  printf 'export REPO_URL=%q\n' "${REPO_URL}"
  printf 'export REPO_BRANCH=%q\n' "${REPO_BRANCH}"
  printf 'export APP_DIR=%q\n' "${APP_DIR}"
  tail -n +2 "${SCRIPT_DIR}/user-data.sh"
} >"${user_data_file}"

# --- Launch -----------------------------------------------------------------
block_devices="[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":${ROOT_VOLUME_GB},\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true,\"Encrypted\":true}}]"
tags="ResourceType=instance,Tags=[{Key=Name,Value=${INSTANCE_NAME}}]"
vol_tags="ResourceType=volume,Tags=[{Key=Name,Value=${INSTANCE_NAME}}]"

log "Launching ${INSTANCE_TYPE} as ${INSTANCE_NAME}"
instance=""
for attempt in 1 2 3 4 5; do
  if instance="$(aws_cli ec2 run-instances \
    --image-id "${ami_id}" \
    --instance-type "${INSTANCE_TYPE}" \
    --subnet-id "${subnet_id}" \
    --security-group-ids "${sg_id}" \
    --iam-instance-profile "Name=${INSTANCE_PROFILE_NAME}" \
    --associate-public-ip-address \
    --block-device-mappings "${block_devices}" \
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1" \
    --tag-specifications "${tags}" "${vol_tags}" \
    --user-data "file://${user_data_file}" \
    --query 'Instances[0].InstanceId' --output text 2>&1)"; then
    break
  fi
  log "run-instances attempt ${attempt} failed: ${instance}"
  instance=""
  sleep 10
done
[[ -n "${instance}" ]] || die "run-instances failed"
log "Instance ${instance} launched"

wait_instance_state "${instance}" running
log "Public IP: $(instance_public_ip "${instance}")"

if (( WAIT )); then
  log "First boot installs Docker/Compose and builds the image (several minutes)"
  wait_health
  log "Done. Verify: curl ${HEALTH_URL}"
else
  log "Skipping health wait. Logs on instance: /var/log/ai-agent-user-data.log (SSM Session Manager)"
fi
