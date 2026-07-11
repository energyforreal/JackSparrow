#!/usr/bin/env python3
"""Thesis breakout threshold grid on high-confidence B4 evidence (gated)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core.agent_thesis_engine import AgentThesisEngine  # noqa: E402
from scripts.signal_recovery.decision_evidence import (  # noqa: E402
    SWEEP_GATE_MIN_HIGH_CONFIDENCE,
    feature_dict_for_engine,
    filter_high_confidence,
    load_enriched_ndjson,
    provenance_report,
)

ADX_GRID = (25.0, 22.0, 20.0, 18.0)
VOL_GRID = (1.1, 0.9, 0.8, 0.7)


def _binding_blockers(records: List[Any]) -> Dict[str, int]:
    eng = AgentThesisEngine()
    counts: Dict[str, int] = {}
    for rec in filter_high_confidence([r for r in records if r.bucket == "B4"]):
        feats = feature_dict_for_engine(rec)
        nearest = eng.nearest_rule_miss(feats, rec.regime, short_enabled=True)
        if nearest:
            counts[nearest.blocker] = counts.get(nearest.blocker, 0) + 1
    return counts


def _count_breakout_fires(
    records: List[Any],
    *,
    adx_min: float,
    vol_min: float,
) -> Dict[str, Any]:
    from agent.core.config import settings

    eng = AgentThesisEngine()
    orig_adx = float(getattr(settings, "agent_thesis_breakout_adx_min", 25.0) or 25.0)
    orig_vol = float(
        getattr(settings, "agent_thesis_breakout_vol_regime_min", 1.1) or 1.1
    )
    fires = 0
    n = 0
    try:
        settings.agent_thesis_breakout_adx_min = adx_min
        settings.agent_thesis_breakout_vol_regime_min = vol_min
        for rec in filter_high_confidence([r for r in records if r.bucket == "B4"]):
            feats = feature_dict_for_engine(rec)
            if not feats:
                continue
            n += 1
            verdict = eng._eval_breakout_long(feats, rec.regime)
            if verdict is not None:
                fires += 1
    finally:
        settings.agent_thesis_breakout_adx_min = orig_adx
        settings.agent_thesis_breakout_vol_regime_min = orig_vol

    return {
        "agent_thesis_breakout_adx_min": adx_min,
        "agent_thesis_breakout_vol_regime_min": vol_min,
        "analyzed": n,
        "breakout_long_fires": fires,
        "fire_rate_pct": round(fires / max(n, 1) * 100.0, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="Run even if sweep gate FAIL")
    args = parser.parse_args()

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_json = args.out_json or (
        ROOT / "data" / "investigation" / f"threshold_sweep_{date_tag}.json"
    )

    records = load_enriched_ndjson(args.evidence_json)
    coverage = provenance_report(records)
    gate = coverage.get("sweep_gate")
    if gate != "PASS" and not args.force:
        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "skipped",
            "reason": f"sweep_gate={gate}; need N>={SWEEP_GATE_MIN_HIGH_CONFIDENCE}",
            "coverage": coverage,
        }
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
        return 0

    binding = _binding_blockers(records)
    grid = [_count_breakout_fires(records, adx_min=adx, vol_min=vol) for adx in ADX_GRID for vol in VOL_GRID]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "coverage": coverage,
        "binding_blockers_high_confidence": binding,
        "grid": grid,
        "note": (
            "Counts hypothetical breakout_long fires on enriched B4 features. "
            "Full EV validation requires counterfactual replay extension — not production change."
        ),
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md_path = ROOT / "data" / "investigation" / f"threshold_sweep_{date_tag}.md"
    lines = [
        "# Thesis Threshold Sweep (Evidence-Based)",
        "",
        f"Gate: {gate}",
        f"High-confidence B4: {coverage.get('high_confidence')}",
        "",
        "## Binding blockers (baseline thresholds)",
        "",
        *[f"- {k}: {v}" for k, v in sorted(binding.items(), key=lambda x: -x[1])],
        "",
        "## Grid — breakout_long fire rate",
        "",
        "| ADX min | Vol min | Fires | Analyzed | Fire % |",
        "|--------:|--------:|------:|---------:|-------:|",
    ]
    for row in grid:
        lines.append(
            f"| {row['agent_thesis_breakout_adx_min']} | {row['agent_thesis_breakout_vol_regime_min']} | "
            f"{row['breakout_long_fires']} | {row['analyzed']} | {row['fire_rate_pct']} |"
        )
    lines.append("")
    lines.append(report["note"])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": "completed", "grid_points": len(grid), "out_json": str(out_json)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
