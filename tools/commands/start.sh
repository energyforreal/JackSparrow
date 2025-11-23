#!/bin/bash
# Start all JackSparrow services
# Uses Python-based parallel process manager for simultaneous startup

set -e

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

