#!/usr/bin/env python3
"""Shadow latent scoring counterfactual evaluation from decision telemetry."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core.latent_scoring import compute_latent_score  # noqa: E402
from agent.core.signal_vocabulary import is_entry_signal, normalize_signal  # noqa: E402
from scripts.signal_recovery.log_parser import filter_since, load_telemetry  # noqa: E402


def _pnl_proxy(row: Dict[str, Any], direction: str) -> float:
    er = float(row.get("expected_return") or 0.0)
    scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
    size = float(scores.get("size_fraction") or scores.get("policy_confidence") or 0.05)
    sign = 1.0 if direction == "LONG" else -1.0
    return sign * er * size


def evaluate_shadow(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    production_pnl = 0.0
    shadow_pnl = 0.0
    agree = disagree = 0
    policy_signals: Counter = Counter()
    shadow_signals: Counter = Counter()
    disagreements: List[Dict[str, Any]] = []

    for r in rows:
        latent = r.get("latent") if isinstance(r.get("latent"), dict) else {}
        extra = r.get("extra") if isinstance(r.get("extra"), dict) else {}
        shadow_block = extra.get("latent_shadow") if isinstance(extra.get("latent_shadow"), dict) else {}

        policy_sig = normalize_signal(r.get("signal") or "HOLD")
        policy_signals[policy_sig] += 1

        if shadow_block:
            shadow_sig = normalize_signal(shadow_block.get("shadow_signal") or "HOLD")
        else:
            result = compute_latent_score(
                expected_return=float(r.get("expected_return") or r.get("proba") or 0.0),
                threshold=float(r.get("threshold") or 0.0),
                kappa=float(latent.get("kappa_ml") or r.get("confidence") or 0.5),
                trade_score=float(r.get("trade_score") or 50.0),
                agreement=float(latent.get("A_composite") or 0.0),
                policy_signal=policy_sig,
            )
            shadow_sig = normalize_signal(result.shadow_signal)

        shadow_signals[shadow_sig] += 1

        if is_entry_signal(policy_sig):
            production_pnl += _pnl_proxy(r, "LONG" if "BUY" in policy_sig or policy_sig == "LONG" else "SHORT")
        if is_entry_signal(shadow_sig):
            shadow_pnl += _pnl_proxy(
                r,
                "LONG" if shadow_sig in ("LONG", "BUY", "STRONG_BUY", "WEAK_BUY") else "SHORT",
            )

        if shadow_sig == policy_sig:
            agree += 1
        else:
            disagree += 1
            if len(disagreements) < 50:
                disagreements.append(
                    {
                        "ts": r.get("ts"),
                        "policy": policy_sig,
                        "shadow": shadow_sig,
                        "score_s": shadow_block.get("score_s") if shadow_block else None,
                    }
                )

    n = len(rows) or 1
    return {
        "sample_count": len(rows),
        "agreement_rate": round(agree / n, 4),
        "disagreement_rate": round(disagree / n, 4),
        "production_pnl_proxy": round(production_pnl, 6),
        "shadow_pnl_proxy": round(shadow_pnl, 6),
        "shadow_beats_production": shadow_pnl > production_pnl,
        "policy_signal_histogram": dict(policy_signals),
        "shadow_signal_histogram": dict(shadow_signals),
        "sample_disagreements": disagreements,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=168.0)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "shadow_eval_report.json",
    )
    args = parser.parse_args()

    rows = filter_since(load_telemetry(args.telemetry), args.hours)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": args.hours,
        **evaluate_shadow(rows),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
