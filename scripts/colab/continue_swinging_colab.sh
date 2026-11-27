#!/usr/bin/env bash
# Continue swinging training after notebook 03 on the existing Colab session.
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SESSION="${SESSION:-swinging}"
TIMEOUT_SEC="${TIMEOUT_SEC:-28800}"
LOCAL_EXPORT_DIR="${REPO_ROOT}/export/swinging"

echo "Waiting until session ${SESSION} is idle..."
while true; do
  text="$(colab status -s "${SESSION}" 2>&1 || true)"
  printf '%s\n' "${text}"
  if printf '%s\n' "${text}" | grep -Fq "No active"; then
    echo "Session ${SESSION} is gone." >&2
    exit 1
  fi
  if ! printf '%s\n' "${text}" | grep -Fq "BUSY"; then
    break
  fi
  sleep 120
done

echo "Session idle."
colab ls -s "${SESSION}" JackSparrow/data/BTCUSD/5m || true

run_notebook() {
  local notebook="$1"
  local path="${SCRIPT_DIR}/${notebook}"
  echo "Executing ${notebook} (timeout=${TIMEOUT_SEC}s)..."
  colab exec -s "${SESSION}" -f "${path}" --timeout "${TIMEOUT_SEC}"
  echo "Finished ${notebook}"
}

if ! colab ls -s "${SESSION}" JackSparrow/data/BTCUSD/5m/setups.parquet >/dev/null 2>&1; then
  echo "Setup parquet is missing. Rerunning notebook 03."
  run_notebook "03_algorithmic_setup_generation.ipynb"
fi

for notebook in \
  04_trade_outcome_engine.ipynb \
  05_setup_effectiveness_training.ipynb \
  06_sr_effectiveness_training.ipynb \
  07_walk_forward_backtesting.ipynb \
  08_model_export.ipynb
do
  run_notebook "${notebook}"
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
