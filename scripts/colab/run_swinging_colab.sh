#!/usr/bin/env bash
# Train the swinging research models on one Colab VM.
# Notebooks 01-08 share /content/JackSparrow/data, so they run in order.
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SESSION="${SESSION:-swinging}"
TIMEOUT_SEC="${TIMEOUT_SEC:-28800}"
GPU="${GPU:-none}"
LOCAL_EXPORT_DIR="${REPO_ROOT}/export/swinging"

NOTEBOOKS=(
  "01_delta_historical_data.ipynb"
  "02_feature_engineering.ipynb"
  "03_algorithmic_setup_generation.ipynb"
  "04_trade_outcome_engine.ipynb"
  "05_setup_effectiveness_training.ipynb"
  "06_sr_effectiveness_training.ipynb"
  "07_walk_forward_backtesting.ipynb"
  "08_model_export.ipynb"
)

if ! command -v colab >/dev/null 2>&1; then
  echo "colab CLI not found on PATH" >&2
  exit 1
fi

session_exists() {
  colab sessions 2>/dev/null | grep -Fq "${SESSION}"
}

echo "Provisioning Colab session ${SESSION} (gpu=${GPU})..."
if session_exists; then
  echo "Reusing existing session ${SESSION}"
else
  new_args=(new -s "${SESSION}")
  if [[ "${GPU}" != "none" ]]; then
    new_args+=(--gpu "${GPU}")
  fi
  provision_ok=0
  for attempt in 1 2 3 4 5; do
    echo "Assign attempt ${attempt}/5..."
    if colab "${new_args[@]}"; then
      if session_exists; then
        provision_ok=1
        break
      fi
    fi
    echo "Assign failed. Retrying in 30s..."
    sleep 30
  done
  if [[ "${provision_ok}" -ne 1 ]]; then
    echo "Could not provision session ${SESSION}." >&2
    exit 1
  fi
fi

echo "Open in browser:"
colab url -s "${SESSION}" || true

for notebook in "${NOTEBOOKS[@]}"; do
  path="${SCRIPT_DIR}/${notebook}"
  if [[ ! -f "${path}" ]]; then
    echo "Notebook not found: ${path}" >&2
    exit 1
  fi
  echo "Executing ${notebook} (timeout=${TIMEOUT_SEC}s)..."
  colab exec -s "${SESSION}" -f "${path}" --timeout "${TIMEOUT_SEC}"
  echo "Finished ${notebook}"
done

mkdir -p "${LOCAL_EXPORT_DIR}"
download_one() {
  local remote="$1"
  local local_path="$2"
  echo "Downloading ${remote} -> ${local_path}"
  colab download -s "${SESSION}" "${remote}" "${local_path}"
}

download_one "JackSparrow/data/export/setup_effectiveness.zip" \
  "${LOCAL_EXPORT_DIR}/setup_effectiveness.zip"
download_one "JackSparrow/data/export/sr_effectiveness.zip" \
  "${LOCAL_EXPORT_DIR}/sr_effectiveness.zip"
download_one "JackSparrow/data/experiments/comparison.json" \
  "${LOCAL_EXPORT_DIR}/comparison.json" || true

echo "Research zips are in ${LOCAL_EXPORT_DIR}"
echo "Stopping Colab session ${SESSION}..."
colab stop -s "${SESSION}" || true
echo "Swinging Colab training finished."
