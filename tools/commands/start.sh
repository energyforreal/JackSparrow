#!/bin/bash
# Start all JackSparrow services
# Uses Python-based parallel process manager for simultaneous startup

set -e

# Helper: check if a port is open (requires Python, which the project already uses)
check_port() {
  python - "$1" "$2" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
s = socket.socket()
s.settimeout(1)
try:
    s.connect((host, port))
except Exception:
    sys.exit(1)
else:
    sys.exit(0)
finally:
    s.close()
PY
}

# Attempt to start redis-server locally if it's not already reachable
ensure_redis() {
  if check_port "localhost" 6379 >/dev/null 2>&1; then
    echo "✓ Redis reachable on localhost:6379"
    return
  fi

  if command -v redis-server >/dev/null 2>&1; then
    echo "Starting local redis-server instance..."
    redis-server --daemonize yes >/dev/null 2>&1 || true
    sleep 2
    if check_port "localhost" 6379 >/dev/null 2>&1; then
      echo "✓ Redis server started"
    else
      echo "⚠ Unable to confirm Redis startup. Please ensure Redis is running." >&2
    fi
  else
    echo "⚠ Redis not running and redis-server not found in PATH. Start Redis manually or via Docker." >&2
  fi
}

# Ensure Redis is available before launching services
ensure_redis

# Get script directory for proper path resolution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Path to Python parallel startup script
PYTHON_SCRIPT="$SCRIPT_DIR/start_parallel.py"

# Check if Python is available
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "Error: Python is required but not found in PATH" >&2
    echo "Please install Python 3.11+ and ensure it's in your PATH" >&2
    exit 1
fi

# Use python3 if available, otherwise python
PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

# Make Python script executable
chmod +x "$PYTHON_SCRIPT" 2>/dev/null || true

# Execute Python script for parallel startup
echo "Launching parallel process manager..."
exec "$PYTHON_CMD" "$PYTHON_SCRIPT"

