#!/usr/bin/env bash
# Run the standalone next-candle research notebook on a Colab GPU via the
# Google Colab CLI. Must execute inside WSL/Linux (the CLI is not supported
# on native Windows).
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEFAULT_NOTEBOOK="${SCRIPT_DIR}/transformer_btcusd_next_candle_research.ipynb"
BUNDLE_DIR_NAME="JackSparrow_Transformer_BTCUSD_mtf_fusion"
REMOTE_EXPORT_DIR="/content/export/${BUNDLE_DIR_NAME}"
REMOTE_ZIP="/content/export/${BUNDLE_DIR_NAME}.zip"

GPU="T4"
SESSION="mtf-fusion"
NOTEBOOK="${DEFAULT_NOTEBOOK}"
LOCAL_EXPORT_DIR="${REPO_ROOT}/export"
KEEP=0
STOP_EXISTING=0
TIMEOUT_SEC="28800"

usage() {
  cat <<'EOF'
Usage: run_colab_cli.sh [options]

Provision a Colab runtime from WSL, execute the fused next-candle research
notebook, download the export zip, and tear down the VM.

Options:
  --gpu GPU          Accelerator: T4 (default), L4, G4, H100, A100, or none
  --session NAME     Colab session name (default: mtf-fusion)
  --notebook PATH    Local .ipynb to execute (default: next-candle research)
  --export-dir PATH  Local directory for downloaded artifacts (default: export/)
  --timeout SEC      colab exec timeout in seconds (default: 28800 = 8h)
  --keep             Leave the VM running after the job
  --stop-existing    Stop a leftover session with the same name first
  -h, --help         Show this help

First-time Google login is a copy-paste OAuth flow from `colab new`.
The CLI default exec timeout is 30s; this wrapper raises it so training can finish.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu)
      GPU="${2:?}"
      shift 2
      ;;
    --session)
      SESSION="${2:?}"
      shift 2
      ;;
    --notebook)
      NOTEBOOK="${2:?}"
      shift 2
      ;;
    --export-dir)
      LOCAL_EXPORT_DIR="${2:?}"
      shift 2
      ;;
    --timeout)
      TIMEOUT_SEC="${2:?}"
      shift 2
      ;;
    --keep)
      KEEP=1
      shift
      ;;
    --stop-existing)
      STOP_EXISTING=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v colab >/dev/null 2>&1; then
  echo "colab CLI not found on PATH. From Windows PowerShell run:" >&2
  echo "  powershell -File scripts/colab/setup_wsl_colab_cli.ps1" >&2
  exit 1
fi

if [[ ! -f "${NOTEBOOK}" ]]; then
  echo "Notebook not found: ${NOTEBOOK}" >&2
  exit 1
fi

mkdir -p "${LOCAL_EXPORT_DIR}"
SESSION_STARTED=0
DOWNLOAD_OK=0

cleanup() {
  if [[ "${KEEP}" -eq 0 && "${SESSION_STARTED}" -eq 1 && "${DOWNLOAD_OK}" -eq 1 ]]; then
    echo "Stopping Colab session ${SESSION}..."
    colab stop -s "${SESSION}" || true
  elif [[ "${SESSION_STARTED}" -eq 1 ]]; then
    echo "Session ${SESSION} left running (download failed or --keep)."
    colab status -s "${SESSION}" || true
  fi
}
trap cleanup EXIT

new_args=(new -s "${SESSION}")
if [[ "${GPU}" != "none" ]]; then
  new_args+=(--gpu "${GPU}")
fi

if [[ "${STOP_EXISTING}" -eq 1 ]]; then
  colab stop -s "${SESSION}" >/dev/null 2>&1 || true
fi

session_exists() {
  colab sessions 2>/dev/null | grep -Fq "${SESSION}"
}

colab_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  fi
}

classify_provision_text() {
  local log_text="$1"
  local py rotator
  py="$(colab_python)"
  rotator="${SCRIPT_DIR}/rotate_colab_accounts.py"
  if [[ -z "${py}" || ! -f "${rotator}" ]]; then
    echo "other"
    return 0
  fi
  "${py}" "${rotator}" classify --text "${log_text}" 2>/dev/null || true
}

suggest_next_google_account() {
  local log_text="$1"
  local py rotator kind
  py="$(colab_python)"
  rotator="${SCRIPT_DIR}/rotate_colab_accounts.py"
  if [[ -z "${py}" || ! -f "${rotator}" ]]; then
    return 0
  fi
  kind="$(classify_provision_text "${log_text}")"
  if [[ "${kind}" != "quota" ]]; then
    return 0
  fi
  echo "GPU quota detected on the current Google account." >&2
  if [[ -f "${SCRIPT_DIR}/colab_accounts.json" ]]; then
    "${py}" "${rotator}" mark-quota >&2 || true
  else
    echo "Configure three emails, then this helper will pick the next account:" >&2
    echo "  python scripts/colab/rotate_colab_accounts.py init" >&2
  fi
}

echo "Provisioning Colab session ${SESSION} (gpu=${GPU})..."
if session_exists; then
  echo "Reusing existing session ${SESSION}"
  SESSION_STARTED=1
else
  provision_ok=0
  provision_log=""
  for attempt in 1 2 3 4 5; do
    echo "Assign attempt ${attempt}/5..."
    new_out="$(colab "${new_args[@]}" 2>&1 || true)"
    printf '%s\n' "${new_out}"
    provision_log="${provision_log}"$'\n'"${new_out}"
    if printf '%s\n' "${new_out}" | grep -Fq "Backend rejected accelerator"; then
      echo "This Google account cannot use gpu=${GPU}. Try --gpu T4 or --gpu none." >&2
      exit 1
    fi
    kind="$(classify_provision_text "${new_out}")"
    if [[ "${kind}" == "quota" ]]; then
      echo "GPU usage limit on this Google account; retries will not help." >&2
      suggest_next_google_account "${new_out}"
      exit 1
    fi
    if session_exists; then
      provision_ok=1
      break
    fi
    echo "Colab assign failed or session missing (often 503 GPU capacity). Retrying in 30s..."
    sleep 30
  done
  if [[ "${provision_ok}" -ne 1 ]]; then
    echo "Could not provision session ${SESSION} with gpu=${GPU}." >&2
    echo "Retry later, or try: powershell -File scripts/colab/run_colab_cli.ps1 --gpu L4" >&2
    suggest_next_google_account "${provision_log}"
    exit 1
  fi
  SESSION_STARTED=1
fi

echo "Executing $(basename "${NOTEBOOK}") on ${SESSION} (timeout=${TIMEOUT_SEC}s)..."
colab exec -s "${SESSION}" -f "${NOTEBOOK}" --timeout "${TIMEOUT_SEC}"

LOCAL_ZIP="${LOCAL_EXPORT_DIR}/${BUNDLE_DIR_NAME}.zip"
LOCAL_LOG="${LOCAL_EXPORT_DIR}/${BUNDLE_DIR_NAME}_colab_log.ipynb"

echo "Downloading export zip to ${LOCAL_ZIP}..."
# Jupyter Contents API is rooted at /content; absolute /content/... often 404s.
download_ok=0
for remote in \
  "export/${BUNDLE_DIR_NAME}.zip" \
  "${BUNDLE_DIR_NAME}.zip" \
  "${REMOTE_ZIP}"; do
  echo "Trying remote path ${remote}..."
  if colab download -s "${SESSION}" "${remote}" "${LOCAL_ZIP}"; then
    download_ok=1
    DOWNLOAD_OK=1
    echo "Downloaded ${LOCAL_ZIP}"
    break
  fi
done
if [[ "${download_ok}" -ne 1 ]]; then
  echo "Zip download failed; listing likely export dirs..." >&2
  colab ls -s "${SESSION}" || true
  colab ls -s "${SESSION}" export || true
  colab ls -s "${SESSION}" "${REMOTE_EXPORT_DIR}" || true
  echo "Session left running. Pull with:" >&2
  echo "  wsl -d Ubuntu-24.04 -- colab download -s ${SESSION} export/${BUNDLE_DIR_NAME}.zip ${LOCAL_ZIP}" >&2
  exit 1
fi

colab log -s "${SESSION}" -o "${LOCAL_LOG}" || true
echo "Session log: ${LOCAL_LOG}"
echo "Validate after unzip, then copy into agent/model_storage/${BUNDLE_DIR_NAME}/"
