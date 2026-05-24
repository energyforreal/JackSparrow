#!/usr/bin/env python3
"""JackSparrow v43 recovery plan — operational helpers (P0–P3).

Examples:
  python scripts/v43_recovery_runbook.py verify-config
  python scripts/v43_recovery_runbook.py baseline --hours 6
  python scripts/v43_recovery_runbook.py gate-rejects
  python scripts/v43_recovery_runbook.py ab-plan
  python scripts/v43_recovery_runbook.py ab-compare \\
      --baseline logs/signal_recovery/baseline_regressor_mean.json \\
      --candidate logs/signal_recovery/baseline_meta_calibrator.json
  python scripts/v43_recovery_runbook.py policy-stage
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.signal_recovery.kpi import compare_kpis, compute_baseline_kpis
from scripts.signal_recovery.log_parser import merge_decision_sources

P0_RECOVERY_ENV: Dict[str, str] = {
    "JACKSPARROW_V43_INFERENCE_STACK": "regressor_mean",
    "JACKSPARROW_V43_BLOCK_TRENDING_ENTRIES": "false",
    "JACKSPARROW_V43_NEAR_THRESHOLD_EPSILON": "0.0002",
    "JACKSPARROW_V43_MIN_EDGE_COST_RATIO": "0.5",
    "AGENT_POLICY_MODE": "ml_only",
}

P2_AB_MATRIX: List[Dict[str, Any]] = [
    {
        "window": "A",
        "label": "regressor_mean",
        "env": {"JACKSPARROW_V43_INFERENCE_STACK": "regressor_mean"},
        "soak_hours": 24,
    },
    {
        "window": "B",
        "label": "meta_calibrator",
        "env": {"JACKSPARROW_V43_INFERENCE_STACK": "meta_calibrator"},
        "soak_hours": 24,
    },
]

P3_POLICY_STAGES: List[Dict[str, Any]] = [
    {
        "stage": "P0_validation",
        "AGENT_POLICY_MODE": "ml_only",
        "REQUIRE_STRATEGY_ML_AGREEMENT": "true",
        "note": "Validate gated ML throughput without thesis double-consensus.",
    },
    {
        "stage": "P3_soft_fusion",
        "AGENT_POLICY_MODE": "ml_and_thesis",
        "REQUIRE_STRATEGY_ML_AGREEMENT": "true",
        "AGENT_POLICY_ADOPT_GATED_ML_WHEN_THESIS_NEUTRAL": "true",
        "note": "Re-enable fusion; neutral thesis may adopt gated ML.",
    },
    {
        "stage": "P3_strict_fusion",
        "AGENT_POLICY_MODE": "ml_and_thesis",
        "REQUIRE_STRATEGY_ML_AGREEMENT": "true",
        "note": "Full production fusion after ≥5 trades/day confirmed in soft stage.",
    },
]


def _logs_root() -> Path:
    return Path(os.environ.get("LOGS_ROOT", str(_PROJECT_ROOT / "logs")))


def _default_out() -> Path:
    return _logs_root() / "signal_recovery"


def verify_config() -> Dict[str, Any]:
    """Compare process env (or .env.example defaults) against P0 recovery targets."""
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "P0",
        "targets": P0_RECOVERY_ENV,
        "checks": {},
        "all_match": True,
    }
    for key, expected in P0_RECOVERY_ENV.items():
        actual = os.environ.get(key)
        match = actual is not None and str(actual).lower() == expected.lower()
        if actual is None:
            match = None  # unknown until agent restart with updated env
        report["checks"][key] = {
            "expected": expected,
            "actual": actual,
            "match": match,
        }
        if match is False:
            report["all_match"] = False
    return report


def capture_baseline(*, hours: float, out_dir: Path, tag: str) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    telemetry = _logs_root() / "signal_recovery" / "decision_telemetry.ndjson"
    agent_log = _logs_root() / "agent" / "agent.log"
    rows = merge_decision_sources(
        telemetry_path=telemetry,
        agent_log_path=agent_log,
        hours=hours,
    )
    kpis = compute_baseline_kpis(rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "P0_metrics",
        "tag": tag,
        "window_hours": hours,
        "source_telemetry": str(telemetry),
        "source_agent_log": str(agent_log),
        "kpis": kpis,
    }
    suffix = f"_{tag}" if tag else ""
    out_path = out_dir / f"baseline{suffix}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["output_path"] = str(out_path)
    return report


def gate_reject_summary(*, agent_log: Path) -> Dict[str, Any]:
    script = _PROJECT_ROOT / "scripts" / "analyze_v43_gate_rejects.py"
    if not agent_log.is_file():
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": f"agent log not found: {agent_log}",
        }
    proc = subprocess.run(
        [sys.executable, str(script), str(agent_log)],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "P0_verify",
        "agent_log": str(agent_log),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "exit_code": proc.returncode,
    }


def ab_plan() -> Dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "P2",
        "instructions": (
            "Run window A for 24h, capture baseline with --tag regressor_mean, "
            "switch JACKSPARROW_V43_INFERENCE_STACK=meta_calibrator, restart agent, "
            "run window B 24h, capture with --tag meta_calibrator, then ab-compare."
        ),
        "windows": P2_AB_MATRIX,
        "metrics_to_compare": [
            "actionable_rate",
            "expected_return_std",
            "hold_ratio",
            "decision_entropy",
            "v43_collapse_rate_mean",
        ],
    }


def ab_compare(*, baseline_path: Path, candidate_path: Path) -> Dict[str, Any]:
    baseline_doc = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate_doc = json.loads(candidate_path.read_text(encoding="utf-8"))
    b_kpis = baseline_doc.get("kpis") or baseline_doc
    c_kpis = candidate_doc.get("kpis") or candidate_doc
    comparison = compare_kpis(b_kpis, c_kpis)
    winner_hints: List[str] = []
    a_rate_b = b_kpis.get("actionable_rate")
    a_rate_c = c_kpis.get("actionable_rate")
    er_std_b = b_kpis.get("expected_return_std")
    er_std_c = c_kpis.get("expected_return_std")
    if a_rate_b is not None and a_rate_c is not None:
        if a_rate_c > a_rate_b * 1.1:
            winner_hints.append("candidate higher actionable_rate")
        elif a_rate_b > a_rate_c * 1.1:
            winner_hints.append("baseline higher actionable_rate")
    if er_std_b is not None and er_std_c is not None:
        if er_std_c < max(er_std_b * 0.5, 1e-9) and er_std_b > 1e-9:
            winner_hints.append("candidate expected_return_std collapsed — avoid meta_calibrator")
        elif er_std_c > er_std_b:
            winner_hints.append("candidate healthier expected_return dispersion")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "P2",
        "baseline_path": str(baseline_path),
        "candidate_path": str(candidate_path),
        "comparison": comparison,
        "winner_hints": winner_hints,
    }


def policy_stage() -> Dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "P3",
        "stages": P3_POLICY_STAGES,
        "exit_criteria": (
            "Proceed to soft fusion only after P0/P2 show sustained non-zero "
            "gates_passed_long/short and acceptable trades/day."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="JackSparrow v43 recovery runbook")
    ap.add_argument(
        "command",
        choices=(
            "verify-config",
            "baseline",
            "gate-rejects",
            "ab-plan",
            "ab-compare",
            "policy-stage",
            "all-checks",
        ),
    )
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--tag", default="recovery")
    ap.add_argument("--baseline", type=Path, default=None)
    ap.add_argument("--candidate", type=Path, default=None)
    ap.add_argument("--agent-log", type=Path, default=None)
    args = ap.parse_args()

    out_dir = args.out_dir or _default_out()
    agent_log = args.agent_log or (_logs_root() / "agent" / "agent.log")

    if args.command == "verify-config":
        report = verify_config()
    elif args.command == "baseline":
        report = capture_baseline(hours=args.hours, out_dir=out_dir, tag=args.tag)
    elif args.command == "gate-rejects":
        report = gate_reject_summary(agent_log=agent_log)
        gate_path = out_dir / "gate_reject_summary.txt"
        out_dir.mkdir(parents=True, exist_ok=True)
        gate_path.write_text(report.get("stdout", ""), encoding="utf-8")
        report["output_path"] = str(gate_path)
    elif args.command == "ab-plan":
        report = ab_plan()
        plan_path = out_dir / "v43_inference_ab_plan.json"
        out_dir.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["output_path"] = str(plan_path)
    elif args.command == "ab-compare":
        if not args.baseline or not args.candidate:
            print("ab-compare requires --baseline and --candidate", file=sys.stderr)
            return 2
        report = ab_compare(baseline_path=args.baseline, candidate_path=args.candidate)
    elif args.command == "policy-stage":
        report = policy_stage()
        stage_path = out_dir / "v43_policy_staging.json"
        out_dir.mkdir(parents=True, exist_ok=True)
        stage_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["output_path"] = str(stage_path)
    else:
        report = {
            "verify_config": verify_config(),
            "baseline": capture_baseline(hours=args.hours, out_dir=out_dir, tag=args.tag),
            "gate_rejects": gate_reject_summary(agent_log=agent_log),
            "ab_plan": ab_plan(),
            "policy_stage": policy_stage(),
        }

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
