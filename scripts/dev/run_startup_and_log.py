#!/usr/bin/env python3
"""Wrapper to run start_parallel.py and capture all output."""
import sys
import subprocess
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
script_path = project_root / "tools" / "commands" / "start_parallel.py"
log_file = project_root / "startup_full_output.log"

# Run the script and capture all output
with open(log_file, 'w', encoding='utf-8', errors='replace') as f:
    process = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        cwd=str(project_root),
        bufsize=1
    )
    
    # Also print to console
    try:
        for line in process.stdout:
            line_text = line.rstrip()
            print(line_text, flush=True)
            f.write(line)
            f.flush()
    except KeyboardInterrupt:
        process.terminate()
        print("\nInterrupted")
    
    process.wait()
    f.write(f"\n\nExit code: {process.returncode}\n")

print(f"\nFull output saved to: {log_file}")
