#!/usr/bin/env bash
# Runs ON the instance. Renders ${APP_DIR}/backend/.env from the Secrets Manager
# JSON secret (includes CLOUDFLARE_TUNNEL_TOKEN). Installed as
# /usr/local/bin/ai-agent-render-env by install-host-files.sh.

set -euo pipefail

# shellcheck source=/dev/null
source /etc/ai-agent/demo.env

: "${AWS_REGION:?}"
: "${SECRET_ID:?}"
: "${APP_DIR:?}"

command -v jq >/dev/null 2>&1 || { echo "error: jq not installed" >&2; exit 1; }

secret_json="$(aws --region "${AWS_REGION}" secretsmanager get-secret-value \
  --secret-id "${SECRET_ID}" \
  --query SecretString \
  --output text)"

if ! jq -e 'type == "object"' >/dev/null <<<"${secret_json}"; then
  echo "error: secret ${SECRET_ID} is not a JSON object" >&2
  exit 1
fi

if ! jq -e '(.CLOUDFLARE_TUNNEL_TOKEN // "") != ""' >/dev/null <<<"${secret_json}"; then
  echo "error: secret ${SECRET_ID} has no CLOUDFLARE_TUNNEL_TOKEN" >&2
  exit 1
fi

umask 077
tmp="$(mktemp "${APP_DIR}/backend/.env.XXXXXX")"
# GITHUB_TOKEN is only for git on the host; keep it out of container env.
jq -r 'del(.GITHUB_TOKEN) | to_entries[] | "\(.key)=\(.value | tostring)"' \
  <<<"${secret_json}" >"${tmp}"
chmod 600 "${tmp}"
mv -f "${tmp}" "${APP_DIR}/backend/.env"
echo "rendered ${APP_DIR}/backend/.env ($(wc -l <"${APP_DIR}/backend/.env") keys)"
