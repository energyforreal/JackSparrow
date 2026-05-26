#!/usr/bin/env python3
"""Pre-deploy gate: run scenario harness Tier 1 (pipeline health)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cmd = [sys.executable, str(ROOT / "run_scenario_tests.py")]
    print("Running scenario validation (Tier 1)...")
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        print("Scenario validation FAILED — aborting deploy.", file=sys.stderr)
    else:
        print("Scenario validation passed (Tier 1).")
    return rc


if __name__ == "__main__":
    sys.exit(main())
