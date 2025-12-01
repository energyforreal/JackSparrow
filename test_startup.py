#!/usr/bin/env python3
"""Test script to run start_parallel and capture output."""
import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).parent
script = project_root / "tools" / "commands" / "start_parallel.py"

print("Starting script execution...", flush=True)
print(f"Script path: {script}", flush=True)
print(f"Script exists: {script.exists()}", flush=True)

try:
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(project_root),
        capture_output=False,
        text=True,
        timeout=60
    )
    print(f"\nScript exited with code: {result.returncode}", flush=True)
except subprocess.TimeoutExpired:
    print("\nScript timed out after 60 seconds", flush=True)
except Exception as e:
    print(f"\nError running script: {e}", flush=True)
    import traceback
    traceback.print_exc()
