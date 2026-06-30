#!/usr/bin/env python3
"""Run Phase 0-4 investigation pipeline (baseline, classify, fee-dominance, audits, decision gate)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INVESTIGATION = ROOT / "data" / "investigation"


def _run(cmd: list[str]) -> int:
    print(f"\n>>> {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TLE investigation pipeline")
    parser.add_argument("--start", default="2026-06-29")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--audit-log", default=None)
    parser.add_argument("--skip-replay-api", action="store_true")
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Run via docker compose exec backend (DATABASE_URL internal)",
    )
    args = parser.parse_args()

    if args.docker:
        root = str(ROOT)
        subprocess.call(["docker", "compose", "cp", "tools", "backend:/app/tools"], cwd=root)
        subprocess.call(["docker", "compose", "cp", "data", "backend:/app/data"], cwd=root)
        audit = ROOT / "logs" / "signal_audit"
        if audit.is_dir():
            subprocess.call(
                ["docker", "compose", "cp", str(audit), "backend:/app/logs/signal_audit"],
                cwd=root,
            )
        cmd = [
            "docker",
            "compose",
            "exec",
            "-e",
            "DATABASE_URL=postgresql://jacksparrow:jacksparrow@postgres:5432/trading_agent",
            "backend",
            "python",
            "/app/tools/commands/run_tle_investigation.py",
            "--start",
            args.start,
            "--end",
            args.end,
        ]
        if args.skip_replay_api:
            cmd.append("--skip-replay-api")
        if args.audit_log:
            cmd.extend(["--audit-log", args.audit_log])
        rc = subprocess.call(cmd, cwd=root)
        subprocess.call(
            ["docker", "compose", "cp", "backend:/app/data/investigation/.", "data/investigation/"],
            cwd=root,
        )
        return rc

    INVESTIGATION.mkdir(parents=True, exist_ok=True)
    baseline_out = INVESTIGATION / f"baseline_{args.start}_{args.end}.json"
    class_out = INVESTIGATION / f"classification_{args.start}_{args.end}.json"
    stability_out = INVESTIGATION / f"entry_stability_{args.start}_{args.end}.json"
    replay_out = INVESTIGATION / f"replay_{args.start}_{args.end}.json"
    decision_out = INVESTIGATION / "decision_gate_report.json"

    audit_args = ["--audit-log", args.audit_log] if args.audit_log else []
    rc = 0

    rc |= _run(
        [
            sys.executable,
            str(ROOT / "tools" / "commands" / "trade_analytics.py"),
            "baseline-capture",
            "--start",
            args.start,
            "--end",
            args.end,
            "--out",
            str(baseline_out),
            *audit_args,
        ]
    )
    rc |= _run(
        [
            sys.executable,
            str(ROOT / "tools" / "commands" / "trade_analytics.py"),
            "fee-dominance",
            "--start",
            args.start,
            "--end",
            args.end,
        ]
    )
    rc |= _run(
        [
            sys.executable,
            str(ROOT / "tools" / "commands" / "trade_analytics.py"),
            "lifecycle-window",
            "--start",
            args.start,
            "--end",
            args.end,
        ]
    )
    classify_cmd = [
        sys.executable,
        str(ROOT / "tools" / "commands" / "classify_lifecycle_exits.py"),
        "--start",
        args.start,
        "--end",
        args.end,
        "--out",
        str(class_out),
    ]
    if args.audit_log:
        classify_cmd.extend(["--audit-log", args.audit_log])
    rc |= _run(classify_cmd)

    stability_cmd = [
        sys.executable,
        str(ROOT / "tools" / "commands" / "audit_entry_stability.py"),
        "--start",
        args.start,
        "--end",
        args.end,
        "--out",
        str(stability_out),
    ]
    if args.audit_log:
        stability_cmd.extend(["--audit-log", args.audit_log])
    rc |= _run(stability_cmd)

    replay_cmd = [
        sys.executable,
        str(ROOT / "tools" / "commands" / "replay_trade_excursions.py"),
        "--start",
        args.start,
        "--end",
        args.end,
        "--out",
        str(replay_out),
    ]
    if not args.skip_replay_api:
        replay_cmd.append("--use-api")
    rc |= _run(replay_cmd)

    rc |= _run(
        [
            sys.executable,
            str(ROOT / "tools" / "commands" / "decision_gate.py"),
            "--baseline",
            str(baseline_out),
            "--classification",
            str(class_out),
            "--out",
            str(decision_out),
        ]
    )

    return min(rc, 1)


if __name__ == "__main__":
    raise SystemExit(main())
