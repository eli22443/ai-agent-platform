#!/bin/bash
# EC2 first-boot script (cloud-init user-data). provision.sh prepends a header
# that exports: AWS_REGION SECRET_ID REPO_URL REPO_BRANCH APP_DIR
#
# No SSH users are created; access is via SSM Session Manager only.

set -euxo pipefail
exec > >(tee -a /var/log/ai-agent-user-data.log) 2>&1

: "${AWS_REGION:?}"
: "${SECRET_ID:?}"
: "${REPO_URL:?}"
: "${REPO_BRANCH:?}"
: "${APP_DIR:?}"

# --- Packages ---------------------------------------------------------------
dnf install -y docker git jq
systemctl enable --now docker.service

# --- Swap (2 GB RAM box builds a Python image) ------------------------------
if [[ ! -f /swapfile ]]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi
swapon -a || true

# --- Current Compose V2 + buildx plugins ------------------------------------
# The distro packages are stale; the EC2 override needs `ports: !reset []`, and
# recent Compose requires buildx for `--build`.
arch="$(uname -m)" # aarch64
case "${arch}" in
  aarch64) compose_asset="docker-compose-linux-aarch64"; buildx_arch="linux-arm64" ;;
  x86_64) compose_asset="docker-compose-linux-x86_64"; buildx_arch="linux-amd64" ;;
  *) echo "unsupported arch ${arch}" >&2; exit 1 ;;
esac

plugin_dir=/usr/local/lib/docker/cli-plugins
mkdir -p "${plugin_dir}"

compose_base="https://github.com/docker/compose/releases/latest/download"
curl -fsSL "${compose_base}/${compose_asset}" -o "${plugin_dir}/docker-compose"
curl -fsSL "${compose_base}/${compose_asset}.sha256" -o /tmp/compose.sha256
(cd "${plugin_dir}" && echo "$(cut -d' ' -f1 /tmp/compose.sha256)  docker-compose" | sha256sum -c -)
chmod +x "${plugin_dir}/docker-compose"

buildx_tag="$(curl -fsSLI -o /dev/null -w '%{url_effective}' \
  https://github.com/docker/buildx/releases/latest | sed 's#.*/tag/##')"
buildx_name="buildx-${buildx_tag}.${buildx_arch}"
buildx_base="https://github.com/docker/buildx/releases/download/${buildx_tag}"
curl -fsSL "${buildx_base}/${buildx_name}" -o "${plugin_dir}/docker-buildx"
curl -fsSL "${buildx_base}/checksums.txt" -o /tmp/buildx.checksums
# checksums.txt uses BSD form: "<sha256> *<filename>"
expected="$(awk -v f="${buildx_name}" '{n=$2; sub(/^\*/,"",n); if (n==f) {print $1; exit}}' /tmp/buildx.checksums)"
[[ -n "${expected}" ]] || { echo "no buildx checksum for ${buildx_name}" >&2; exit 1; }
echo "${expected}  ${plugin_dir}/docker-buildx" | sha256sum -c -
chmod +x "${plugin_dir}/docker-buildx"

docker compose version
docker buildx version

# --- Runtime config for the helper scripts ----------------------------------
mkdir -p /etc/ai-agent
{
  printf 'AWS_REGION=%q\n' "${AWS_REGION}"
  printf 'SECRET_ID=%q\n' "${SECRET_ID}"
  printf 'REPO_URL=%q\n' "${REPO_URL}"
  printf 'REPO_BRANCH=%q\n' "${REPO_BRANCH}"
  printf 'APP_DIR=%q\n' "${APP_DIR}"
} >/etc/ai-agent/demo.env
chmod 644 /etc/ai-agent/demo.env

# --- Clone the repo ---------------------------------------------------------
# Public repos clone anonymously. If that fails, use an optional read-only
# GITHUB_TOKEN from the secret via a root-only git credential store.
if [[ ! -d "${APP_DIR}/.git" ]]; then
  mkdir -p "$(dirname "${APP_DIR}")"
  if ! git clone --branch "${REPO_BRANCH}" "${REPO_URL}" "${APP_DIR}"; then
    token="$(aws --region "${AWS_REGION}" secretsmanager get-secret-value \
      --secret-id "${SECRET_ID}" --query SecretString --output text \
      | jq -r '.GITHUB_TOKEN // empty')"
    [[ -n "${token}" ]] || { echo "clone failed and secret has no GITHUB_TOKEN" >&2; exit 1; }
    host="$(printf '%s' "${REPO_URL}" | sed -E 's#^https://([^/]+)/.*#\1#')"
    umask 077
    printf 'https://x-access-token:%s@%s\n' "${token}" "${host}" >/root/.git-credentials
    git config --global credential.helper store
    git clone --branch "${REPO_BRANCH}" "${REPO_URL}" "${APP_DIR}"
  fi
fi

# --- Helper scripts, systemd unit, first start ------------------------------
bash "${APP_DIR}/infrastructure/ec2/install-host-files.sh"
systemctl start ai-agent.service

echo "user-data complete"
