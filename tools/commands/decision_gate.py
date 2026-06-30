#!/usr/bin/env python3
"""Decision gate: synthesize investigation outputs and recommend next actions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _dominant_trigger(summary: Dict[str, Any], threshold_pct: float = 50.0) -> Optional[str]:
    if not summary:
        return None
    total = sum(v.get("count", 0) for v in summary.values())
    if total <= 0:
        return None
    best_trigger = max(summary.items(), key=lambda x: x[1].get("count", 0))
    pct = best_trigger[1].get("count", 0) / total * 100.0
    if pct >= threshold_pct:
        return str(best_trigger[0])
    return None


def _recommendations(
    baseline: Dict[str, Any],
    classification: Dict[str, Any],
) -> List[str]:
    recs: List[str] = []
    trades = baseline.get("trades") or {}
    fee_dom = int(trades.get("fee_dominated_count") or 0)
    count = int(trades.get("count") or 0)
    if count and fee_dom / count > 0.5:
        recs.append(
            "Reduce lot sizing and/or enable limit entries (Phase 5); "
            "fee-dominated losses exceed 50% of trades."
        )

    summary = classification.get("summary") or {}
    dominant = _dominant_trigger(summary, threshold_pct=50.0)
    if dominant == "opposite_signal":
        recs.append("Review signal flip sensitivity and debounce; opposite signal dominates exits.")
    elif dominant == "health_threshold":
        recs.append(
            "Audit health scoring weights and entry gates before tuning "
            "TRADE_LIFECYCLE_HEALTH_EXIT_MAX."
        )
    elif dominant in ("fsm_broken", "label_untrusted_fsm_likely"):
        recs.append("Audit FSM thesis logic in continuation_thesis.py.")
    elif dominant == "health_and_fsm":
        recs.append("Both health and FSM fire together; fix scoring interaction, not a single threshold.")
    elif dominant is None and summary:
        recs.append(
            "No dominant trigger (~25-35% each): broader review of signal generation "
            "and TLE interaction; do not tune a single parameter."
        )

    if not recs:
        recs.append("Insufficient data for automated recommendation; collect post-fix exits.")
    return recs


def main() -> int:
    parser = argparse.ArgumentParser(description="TLE investigation decision gate")
    parser.add_argument(
        "--baseline",
        default=str(ROOT / "data" / "investigation" / "baseline_2026-06-29_2026-06-30.json"),
    )
    parser.add_argument(
        "--classification",
        default=str(ROOT / "data" / "investigation" / "classification_jun29-30.json"),
    )
    parser.add_argument("--out", default=str(ROOT / "data" / "investigation" / "decision_gate_report.json"))
    args = parser.parse_args()

    baseline = _load_json(Path(args.baseline)) or {}
    classification = _load_json(Path(args.classification)) or {}

    report: Dict[str, Any] = {
        "baseline_ref": args.baseline,
        "classification_ref": args.classification,
        "baseline_summary": baseline.get("trades"),
        "trigger_summary": classification.get("summary") or baseline.get("exit_triggers_audit_heuristic"),
        "dominant_trigger_50pct": _dominant_trigger(classification.get("summary") or {}),
        "recommendations": _recommendations(baseline, classification),
        "config_changes_deferred": True,
        "note": "No .env changes applied automatically; review recommendations before tuning.",
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== Decision Gate Report ===")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
