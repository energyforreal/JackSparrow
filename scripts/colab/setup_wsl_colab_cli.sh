#!/usr/bin/env bash
# Bootstrap Ubuntu WSL for the Google Colab CLI.
# Run as root: wsl -d Ubuntu-24.04 -u root -- bash scripts/colab/setup_wsl_colab_cli.sh
set -euo pipefail

WSL_USER="${WSL_USER:-lohit}"
export DEBIAN_FRONTEND=noninteractive

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this setup as root (wsl -d Ubuntu-24.04 -u root -- bash $0)" >&2
  exit 1
fi

apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  python3 \
  python3-pip \
  python3-venv \
  unzip

if ! id -u "${WSL_USER}" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "${WSL_USER}"
  usermod -aG sudo "${WSL_USER}"
  echo "${WSL_USER} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${WSL_USER}"
  chmod 440 "/etc/sudoers.d/${WSL_USER}"
  echo "Created WSL user ${WSL_USER}"
fi

install_uv_and_colab() {
  local home_dir
  home_dir="$(getent passwd "${WSL_USER}" | cut -d: -f6)"
  if [[ ! -x "${home_dir}/.local/bin/uv" ]]; then
    curl -LsSf https://astral.sh/uv/install.sh | sudo -u "${WSL_USER}" env HOME="${home_dir}" sh
  fi
  sudo -u "${WSL_USER}" env HOME="${home_dir}" PATH="${home_dir}/.local/bin:${PATH}" \
    uv tool install --force --with "jupyter-kernel-client==0.15.0" google-colab-cli
  sudo -u "${WSL_USER}" env HOME="${home_dir}" PATH="${home_dir}/.local/bin:${PATH}" \
    bash -lc 'colab version'
}

install_uv_and_colab

profile_file="$(getent passwd "${WSL_USER}" | cut -d: -f6)/.profile"
if [[ -f "${profile_file}" ]] && ! grep -q '.local/bin' "${profile_file}"; then
  printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "${profile_file}"
fi

echo "OK: google-colab-cli installed for ${WSL_USER}"
echo "Next: wsl --manage Ubuntu-24.04 --set-default-user ${WSL_USER}"
echo "Then authenticate once: wsl -d Ubuntu-24.04 -- bash -lc 'colab sessions'"
