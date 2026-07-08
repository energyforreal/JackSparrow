#!/usr/bin/env python3
"""Capture recovery baseline: gates, TLE observation, cognition snapshot."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.commands.experiment_gate import evaluate_experiment
from tools.commands.phase_readiness_gate import evaluate_gate
from tools.commands.tle_observation_monitor import scan_audit_log


def _cognition_snapshot() -> dict:
    keys = [
        "COGNITION_SELECTOR_ENABLED",
        "COGNITION_SCORER_ENABLED",
        "COGNITION_TEMPORAL_AUTHORITY_ENABLED",
        "COGNITION_SHADOW_ENABLED",
        "COGNITION_EXPECTATION_ENABLED",
    ]
    return {k: os.environ.get(k) for k in keys}


def main() -> int:
    parser = argparse.ArgumentParser(description="Recovery baseline capture")
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "investigation" / "recovery_baseline_2026-07-08.json"),
    )
    args = parser.parse_args()

    tle_live = evaluate_experiment("tle_live_v1")
    entry_tune = evaluate_experiment("entry_tune_v1")
    exit_tune = evaluate_experiment("exit_tune_v1")
    p1 = evaluate_gate("p1_data_integrity", start=None, end=None)

    audit_path = ROOT / "logs" / "agent" / "signal_audit" / "live_audit.md"
    tle_obs = scan_audit_log(audit_path)

    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "phase": "recovery_baseline",
        "gates": {
            "tle_live_v1": tle_live,
            "entry_tune_v1": entry_tune,
            "exit_tune_v1": exit_tune,
            "p1_data_integrity": p1,
        },
        "tle_observation": tle_obs,
        "cognition_snapshot": _cognition_snapshot(),
        "recovery_actions_applied": {
            "TRADE_LIFECYCLE_LOG_ONLY": os.environ.get("TRADE_LIFECYCLE_LOG_ONLY", "true"),
            "TRADE_LIFECYCLE_MIN_HOLD_BARS": os.environ.get("TRADE_LIFECYCLE_MIN_HOLD_BARS", "2"),
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
