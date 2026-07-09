#!/usr/bin/env python3
"""Bucket hold_at_synthesis rejects into B1-B4 vs A for Phase 3A.1 gate review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.commands.forensics_rejection_breakdown import (  # noqa: E402
    _iter_json_objects,
    _reason_codes_from_context,
)


def _parse_ts(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _hypothesis_snapshot(obj: Dict[str, Any]) -> Dict[str, Any]:
    mc = obj.get("market_context") if isinstance(obj.get("market_context"), dict) else {}
    hyp = mc.get("hypothesis_snapshot") if isinstance(mc.get("hypothesis_snapshot"), dict) else {}
    if hyp:
        return hyp
    dc = obj.get("decision_context") if isinstance(obj.get("decision_context"), dict) else {}
    hyp2 = dc.get("hypothesis_snapshot") if isinstance(dc.get("hypothesis_snapshot"), dict) else {}
    return hyp2 or {}


def _nearest_before(
    ts_index: List[float],
    rows: List[Dict[str, Any]],
    target_ts: float,
    *,
    max_delta_sec: float = 15.0,
) -> Optional[Dict[str, Any]]:
    if not ts_index:
        return None
    pos = bisect_right(ts_index, target_ts) - 1
    if pos < 0:
        return None
    if target_ts - ts_index[pos] > max_delta_sec:
        return None
    return rows[pos]


@dataclass
class HypothesisBreakdown:
    """Aggregated hypothesis hold buckets."""

    hold_total: int = 0
    buckets: Counter = field(default_factory=Counter)
    b4_v43_gates_passed: int = 0
    shadow_would_block: int = 0
    shadow_agrees_hold: int = 0
    shadow_disagrees: int = 0
    samples: List[Dict[str, Any]] = field(default_factory=list)


def classify_hold_bucket(
    *,
    codes: List[str],
    hyp: Dict[str, Any],
    v43: Optional[Dict[str, Any]],
    cognition: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
) -> str:
    """Assign one primary bucket per hold_at_synthesis event."""
    code_set = set(codes)
    reject_tag = str((v43 or {}).get("reject") or "")
    v43_gates_passed = reject_tag in ("gates_passed_short", "gates_passed_long")
    policy_hold = str((v43 or {}).get("policy_signal") or "HOLD").upper() == "HOLD"

    if "hypothesis_margin_below_min" in code_set:
        return "B3"

    if v43_gates_passed and policy_hold and (
        "hypothesis_no_rule_fired" in code_set or "thesis_no_rule_fired" in code_set
    ):
        return "B4"

    hypotheses = hyp.get("hypotheses") if isinstance(hyp.get("hypotheses"), list) else []
    eligible = list((cognition or {}).get("eligible_profiles") or [])
    long_p = float(hyp.get("long_pressure") or 0.0)
    short_p = float(hyp.get("short_pressure") or 0.0)
    total_pressure = long_p + short_p

    if not hypotheses or (cognition is not None and not eligible):
        return "B1"

    if hypotheses and total_pressure <= 1e-9:
        return "B2"

    rb = str((shadow or {}).get("rule_based_signal") or "HOLD").upper()
    live = str((shadow or {}).get("live_signal") or "HOLD").upper()
    if rb == "HOLD" and live == "HOLD":
        return "A"

    if "hypothesis_no_rule_fired" in code_set:
        return "B2"
    return "unknown"


def analyze_log_content(content: str) -> HypothesisBreakdown:
    """Parse agent log and bucket hold_at_synthesis events."""
    v43_rows: List[Dict[str, Any]] = []
    v43_ts: List[float] = []
    cog_rows: List[Dict[str, Any]] = []
    cog_ts: List[float] = []
    shadow_rows: List[Dict[str, Any]] = []
    shadow_ts: List[float] = []

    holds: List[Dict[str, Any]] = []

    for obj in _iter_json_objects(content):
        event = str(obj.get("event") or obj.get("message") or "")
        ts = _parse_ts(obj.get("timestamp"))

        if event == "mcp_orchestrator_v43_prediction_complete" and ts is not None:
            v43_rows.append(obj)
            v43_ts.append(ts)
        elif event == "cognition_thesis_authority_compare" and ts is not None:
            cog_rows.append(obj)
            cog_ts.append(ts)
        elif event == "rule_based_pipeline_shadow" and ts is not None:
            shadow_rows.append(obj)
            shadow_ts.append(ts)
        elif event == "trading_entry_rejected" and str(obj.get("reason")) == "hold_at_synthesis":
            holds.append(obj)

    report = HypothesisBreakdown(hold_total=len(holds))

    for hold in holds:
        ts = _parse_ts(hold.get("timestamp"))
        if ts is None:
            report.buckets["unknown"] += 1
            continue

        v43 = _nearest_before(v43_ts, v43_rows, ts)
        cognition = _nearest_before(cog_ts, cog_rows, ts)
        shadow = _nearest_before(shadow_ts, shadow_rows, ts)

        codes = _reason_codes_from_context(hold)
        hyp = _hypothesis_snapshot(hold)
        bucket = classify_hold_bucket(
            codes=codes,
            hyp=hyp,
            v43=v43,
            cognition=cognition,
            shadow=shadow,
        )
        report.buckets[bucket] += 1

        reject_tag = str((v43 or {}).get("reject") or "")
        if reject_tag in ("gates_passed_short", "gates_passed_long"):
            if "hypothesis_no_rule_fired" in codes and str(
                (v43 or {}).get("policy_signal") or "HOLD"
            ).upper() == "HOLD":
                report.b4_v43_gates_passed += 1

        if shadow:
            if shadow.get("would_block_live_entry"):
                report.shadow_would_block += 1
            rb = str(shadow.get("rule_based_signal") or "HOLD").upper()
            live = str(shadow.get("live_signal") or "HOLD").upper()
            if rb == "HOLD" and live == "HOLD":
                report.shadow_agrees_hold += 1
            elif rb != live:
                report.shadow_disagrees += 1

        if len(report.samples) < 30:
            report.samples.append(
                {
                    "event_id": hold.get("event_id"),
                    "timestamp": hold.get("timestamp"),
                    "bucket": bucket,
                    "v43_reject": reject_tag,
                    "v43_policy_signal": (v43 or {}).get("policy_signal"),
                    "eligible_profiles": (cognition or {}).get("eligible_profiles"),
                    "hypothesis_count": len(hyp.get("hypotheses") or []),
                    "long_pressure": hyp.get("long_pressure"),
                    "short_pressure": hyp.get("short_pressure"),
                    "shadow_rule_based": (shadow or {}).get("rule_based_signal"),
                    "top_codes": codes[:6],
                }
            )

    return report


def _pct(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total * 100.0, 2)


def evaluate_gate(report: HypothesisBreakdown) -> Dict[str, Any]:
    """Apply Phase 3A.1 exit criteria."""
    total = report.hold_total or 1
    b1 = report.buckets.get("B1", 0)
    b2 = report.buckets.get("B2", 0)
    b3 = report.buckets.get("B3", 0)
    b4 = report.buckets.get("B4", 0)
    a_bucket = report.buckets.get("A", 0)
    b1b2_pct = _pct(b1 + b2, total)
    b4_pct = _pct(b4, total)
    a_pct = _pct(a_bucket, total)

    if b4_pct > 30.0:
        decision = "proceed_3a2"
        rationale = f"B4 share {b4_pct}% exceeds 30% gate — policy semantics review justified."
    elif b1b2_pct > 50.0:
        decision = "defer_3a2_fix_upstream"
        rationale = (
            f"B1+B2 share {b1b2_pct}% exceeds 50% — fix selector/scorer upstream before 3A.2."
        )
    elif a_pct > 70.0:
        decision = "skip_3a2"
        rationale = f"Shadow-agrees bucket A {a_pct}% exceeds 70% — conservatism is appropriate."
    else:
        decision = "review_mixed"
        rationale = "No single gate threshold met; manual review of bucket mix recommended."

    return {
        "decision": decision,
        "rationale": rationale,
        "thresholds": {
            "b4_proceed_pct": 30.0,
            "b1_b2_defer_pct": 50.0,
            "a_skip_pct": 70.0,
        },
        "observed_pct": {
            "B1": _pct(b1, total),
            "B2": _pct(b2, total),
            "B3": _pct(b3, total),
            "B4": b4_pct,
            "A": a_pct,
            "B1_B2_combined": b1b2_pct,
        },
    }


def build_output(report: HypothesisBreakdown, *, log_file: Path) -> Dict[str, Any]:
    """Build JSON output for investigation artifacts."""
    total = report.hold_total or 1
    bucket_rows = [
        {"bucket": k, "count": v, "pct": _pct(v, total)}
        for k, v in sorted(report.buckets.items(), key=lambda x: -x[1])
    ]
    gate = evaluate_gate(report)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_log": str(log_file),
        "hold_at_synthesis_total": report.hold_total,
        "bucket_histogram": bucket_rows,
        "shadow_analysis": {
            "agrees_hold": report.shadow_agrees_hold,
            "would_block_live_entry": report.shadow_would_block,
            "disagrees_with_live": report.shadow_disagrees,
            "agrees_hold_pct": _pct(report.shadow_agrees_hold, total),
        },
        "b4_v43_gates_passed_hold": report.b4_v43_gates_passed,
        "gate_decision": gate,
        "samples": report.samples,
        "bucket_definitions": {
            "B1": "hypothesis_no_rule_fired + zero candidates / empty eligible_profiles",
            "B2": "candidates exist but total pressure <= 1e-9",
            "B3": "hypothesis_margin_below_min",
            "B4": "v43 gates_passed_* but policy HOLD with flat hypothesis",
            "A": "rule_based shadow agrees with live HOLD",
        },
    }


def format_summary(data: Dict[str, Any]) -> str:
    lines = [
        "=== Hypothesis Breakdown (3A.1) ===",
        f"Hold at synthesis: {data.get('hold_at_synthesis_total', 0)}",
        "",
        "Buckets:",
    ]
    for row in data.get("bucket_histogram") or []:
        lines.append(f"  {row['bucket']}: {row['count']} ({row['pct']}%)")
    gate = data.get("gate_decision") or {}
    lines.extend(
        [
            "",
            f"Gate decision: {gate.get('decision')}",
            f"Rationale: {gate.get('rationale')}",
            "",
            "Shadow:",
            json.dumps(data.get("shadow_analysis"), indent=2),
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_file", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "investigation" / "hypothesis_breakdown_2026-07-09.json",
    )
    parser.add_argument(
        "--gate-doc",
        type=Path,
        default=ROOT / "data" / "investigation" / "phase3_gate_decision_3a1.md",
    )
    args = parser.parse_args()

    content = args.log_file.read_text(encoding="utf-8", errors="replace")
    report = analyze_log_content(content)
    output = build_output(report, log_file=args.log_file)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")

    gate_md = [
        "# Phase 3A.1 Gate Decision",
        "",
        f"Generated: {output['generated_at']}",
        f"Source log: `{args.log_file}`",
        "",
        "## Bucket histogram",
        "",
        "| Bucket | Count | % |",
        "|--------|------:|--:|",
    ]
    for row in output["bucket_histogram"]:
        gate_md.append(f"| {row['bucket']} | {row['count']} | {row['pct']}% |")
    gate = output["gate_decision"]
    gate_md.extend(
        [
            "",
            "## Gate outcome",
            "",
            f"**Decision:** `{gate['decision']}`",
            "",
            gate["rationale"],
            "",
            "## Next step",
            "",
        ]
    )
    decision = gate["decision"]
    if decision == "proceed_3a2":
        gate_md.append(
            "Proceed to 3A.2: enable `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` "
            "on isolated testnet (48–72h)."
        )
    elif decision == "defer_3a2_fix_upstream":
        gate_md.append(
            "Defer 3A.2. Tune cognition selector / hypothesis scorer upstream (B1/B2 path)."
        )
    elif decision == "skip_3a2":
        gate_md.append("Skip 3A.2. Focus on hypothesis rule tuning or accept conservatism.")
    else:
        gate_md.append("Manual review — mixed bucket distribution; see samples in JSON artifact.")

    args.gate_doc.write_text("\n".join(gate_md), encoding="utf-8")
    print(format_summary(output))
    print(f"\nWrote {args.out}")
    print(f"Wrote {args.gate_doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
