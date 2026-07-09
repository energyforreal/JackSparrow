#!/usr/bin/env python3
"""Run daily Phase 3 forensics bundle for an active testnet experiment."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str]) -> int:
    print(f"\n>>> {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workstream", required=True, help="e.g. 3a1, 3a2, 3b")
    parser.add_argument(
        "--log-out",
        type=Path,
        default=None,
        help="Agent log export path (default: data/investigation/agent_exp_<ws>_<date>.log)",
    )
    parser.add_argument(
        "--docker-container",
        default="jacksparrow-agent",
        help="Agent container name for docker logs export",
    )
    args = parser.parse_args()

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_out = args.log_out or (
        ROOT / "data" / "investigation" / f"agent_exp_{args.workstream}_{date_tag}.log"
    )
    log_out.parent.mkdir(parents=True, exist_ok=True)

    export_cmd = [
        "docker",
        "logs",
        args.docker_container,
        "--since",
        "24h",
    ]
    print(f">>> docker logs ... > {log_out}")
    with log_out.open("w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.run(export_cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        print(f"docker logs export failed: {proc.returncode}", file=sys.stderr)
        return proc.returncode

    inv = ROOT / "data" / "investigation"
    steps = [
        [sys.executable, "tools/commands/forensics_rejection_breakdown.py", str(log_out)],
        [
            sys.executable,
            "tools/commands/forensics_hypothesis_breakdown.py",
            str(log_out),
            "--out",
            str(inv / f"hypothesis_breakdown_{date_tag}.json"),
        ],
        [sys.executable, "tools/commands/reconcile_risk_approvals.py", str(log_out)],
    ]
    rc = 0
    for cmd in steps:
        rc = _run(cmd) or rc
    print(f"\nDaily forensics complete for workstream {args.workstream}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
