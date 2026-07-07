#!/usr/bin/env python3
"""Check tle_live_v1 gate and print promotion steps (does not modify .env)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.commands.experiment_gate import evaluate_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description="TLE live promotion readiness")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()

    result = evaluate_experiment("tle_live_v1", start=args.start, end=args.end)
    steps = {
        "experiment": result,
        "promotion_steps_if_pass": [
            "Set TRADE_LIFECYCLE_LOG_ONLY=false in .env",
            "docker compose up -d --build agent",
            "Monitor trade_lifecycle_verdict for first 20 actions",
            "python tools/commands/phase_readiness_gate.py --gate 3_to_4",
        ],
        "rollback": "python tools/commands/tle_promotion_rollback.py",
    }
    print(json.dumps(steps, indent=2))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
