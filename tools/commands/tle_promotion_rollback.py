#!/usr/bin/env python3
"""Rollback helper when live TLE promotion degrades performance."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="TLE live promotion rollback checklist")
    parser.add_argument("--reason", default="performance_degradation")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    checklist = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reason": args.reason,
        "immediate_actions": [
            "Set TRADE_LIFECYCLE_LOG_ONLY=true in .env",
            "Restart jacksparrow-agent container",
            "Verify trade_lifecycle_verdict actions stop executing (log only)",
        ],
        "verification": [
            "python tools/commands/tle_observation_monitor.py",
            "python tools/commands/experiment_gate.py --experiment tle_live_v1",
        ],
        "note": "Mechanical SL/TP/trailing in manage_position remains active after rollback.",
    }
    text = json.dumps(checklist, indent=2)
    print(text)
    out = Path(args.out) if args.out else ROOT / "data" / "investigation" / "tle_rollback_checklist.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
