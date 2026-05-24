#!/usr/bin/env python3
"""JackSparrow signal recovery plan — run all phases or individual steps.

Examples:
  python scripts/signal_recovery/run.py all
  python scripts/signal_recovery/run.py phase1
  python scripts/signal_recovery/run.py baseline --hours 24
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.signal_recovery.phase1_verify_pipeline import run_phase1
from scripts.signal_recovery.phase2_baseline import run_phase2
from scripts.signal_recovery.phase3_meta_ablation import run_meta_ablation
from scripts.signal_recovery.phase3_label_experiments import run_label_experiments
from scripts.signal_recovery.phase3_execution_ablation import run_execution_ablation
from scripts.signal_recovery.phase4_drift_features import run_drift_diagnostics
from scripts.signal_recovery.phase5_promotion_gates import run_promotion_gates


def _logs_root() -> Path:
    return Path(os.environ.get("LOGS_ROOT", str(_PROJECT_ROOT / "logs")))


def _default_out() -> Path:
    return _logs_root() / "signal_recovery"


def main() -> int:
    ap = argparse.ArgumentParser(description="JackSparrow signal recovery tooling")
    ap.add_argument(
        "command",
        choices=(
            "all",
            "phase1",
            "baseline",
            "meta-ablation",
            "labels",
            "execution",
            "drift",
            "promotion",
        ),
    )
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--hours", type=float, default=24.0, help="Baseline window (hours)")
    ap.add_argument("--backend", default="http://127.0.0.1:8000")
    ap.add_argument("--agent-log", type=Path, default=None)
    ap.add_argument("--baseline", type=Path, default=None, help="For promotion gates")
    ap.add_argument("--candidate", type=Path, default=None, help="For promotion gates")
    args = ap.parse_args()

    out_dir = args.out_dir or _default_out()
    agent_log = args.agent_log or (_logs_root() / "agent" / "agent.log")
    telemetry = _logs_root() / "signal_recovery" / "decision_telemetry.ndjson"

    if args.command == "phase1":
        report = run_phase1(backend_base=args.backend, agent_log=agent_log, out_dir=out_dir)
    elif args.command == "baseline":
        report = run_phase2(
            telemetry_path=telemetry,
            agent_log=agent_log,
            out_dir=out_dir,
            hours=args.hours,
        )
    elif args.command == "meta-ablation":
        report = run_meta_ablation(out_dir=out_dir)
    elif args.command == "labels":
        report = run_label_experiments(out_dir=out_dir)
    elif args.command == "execution":
        report = run_execution_ablation(out_dir=out_dir)
    elif args.command == "drift":
        report = run_drift_diagnostics(out_dir=out_dir)
    elif args.command == "promotion":
        baseline = args.baseline or (out_dir / "baseline_kpis.json")
        candidate = args.candidate or (out_dir / "meta_ablation_report.json")
        report = run_promotion_gates(
            baseline_path=baseline,
            candidate_path=candidate,
            out_dir=out_dir,
            agent_log=agent_log,
        )
    else:
        reports = {}
        reports["phase1"] = run_phase1(
            backend_base=args.backend, agent_log=agent_log, out_dir=out_dir
        )
        reports["phase2"] = run_phase2(
            telemetry_path=telemetry,
            agent_log=agent_log,
            out_dir=out_dir,
            hours=args.hours,
        )
        reports["phase3_meta"] = run_meta_ablation(out_dir=out_dir)
        reports["phase3_labels"] = run_label_experiments(out_dir=out_dir)
        reports["phase3_execution"] = run_execution_ablation(out_dir=out_dir)
        reports["phase4"] = run_drift_diagnostics(out_dir=out_dir)
        baseline_path = out_dir / "baseline_kpis.json"
        candidate_path = out_dir / "baseline_kpis.json"
        reports["phase5"] = run_promotion_gates(
            baseline_path=baseline_path,
            candidate_path=candidate_path,
            out_dir=out_dir,
            agent_log=agent_log,
        )
        report = {"phases": list(reports.keys()), "outputs_dir": str(out_dir)}

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
