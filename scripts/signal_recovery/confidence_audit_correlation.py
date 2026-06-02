#!/usr/bin/env python3
"""Correlate live_audit entry_proba fields with step5 vs final confidence.

Usage:
  python scripts/signal_recovery/confidence_audit_correlation.py
  python scripts/signal_recovery/confidence_audit_correlation.py --path logs/agent/signal_audit/live_audit.md
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_KV_RE = re.compile(r"(\w+)=([^;|]+)")


def _parse_kv_segment(segment: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in _KV_RE.finditer(segment):
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key and val:
            out[key] = val
    return out


def parse_live_audit(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "`entry_rejected`" not in line and "`ai_signal`" not in line:
            continue
        kind = "ai_signal" if "`ai_signal`" in line else "entry_rejected"
        pipe_idx = line.find("|", line.find(kind))
        if pipe_idx < 0:
            continue
        kv = _parse_kv_segment(line[pipe_idx + 1 :])
        try:
            conf = float(kv.get("conf") or kv.get("reasoning_final_confidence") or 0)
        except ValueError:
            conf = None
        step5 = kv.get("synthesis_step5_confidence")
        try:
            step5_f = float(step5) if step5 is not None else None
        except ValueError:
            step5_f = None
        sell_mean = kv.get("entry_proba_sell_mean")
        try:
            sell_f = float(sell_mean) if sell_mean is not None else None
        except ValueError:
            sell_f = None
        rows.append(
            {
                "kind": kind,
                "signal": kv.get("signal", "").strip("`"),
                "conf": conf,
                "step5": step5_f,
                "entry_proba_sell_mean": sell_f,
                "hold_bucket": kv.get("hold_bucket"),
                "event_id": kv.get("event_id", "").strip("`"),
            }
        )
    return rows


def correlate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Group by entry_proba fingerprint; flag identical final confidence clusters."""
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("entry_proba_sell_mean") is None:
            continue
        key = f"sell={r['entry_proba_sell_mean']:.8f}|signal={r.get('signal')}"
        groups[key].append(r)

    duplicate_clusters: List[Dict[str, Any]] = []
    for key, items in groups.items():
        confs = [i["conf"] for i in items if i.get("conf") is not None]
        if len(items) < 2 or not confs:
            continue
        if len(set(round(c, 6) for c in confs)) == 1:
            duplicate_clusters.append(
                {
                    "fingerprint": key,
                    "count": len(items),
                    "confidence": confs[0],
                    "step5_samples": list(
                        {i["step5"] for i in items if i.get("step5") is not None}
                    ),
                }
            )

    step5_vs_final: List[Dict[str, float]] = []
    for r in rows:
        if r.get("step5") is not None and r.get("conf") is not None:
            step5_vs_final.append(
                {
                    "delta": float(r["conf"]) - float(r["step5"]),
                    "step5": float(r["step5"]),
                    "final": float(r["conf"]),
                }
            )

    deltas = [x["delta"] for x in step5_vs_final]
    return {
        "total_rows": len(rows),
        "grouped_with_entry_proba": len(groups),
        "duplicate_confidence_clusters": len(duplicate_clusters),
        "clusters": sorted(duplicate_clusters, key=lambda x: -x["count"])[:20],
        "step5_to_final_delta_mean": (sum(deltas) / len(deltas)) if deltas else None,
        "step5_to_final_delta_min": min(deltas) if deltas else None,
        "step5_to_final_delta_max": max(deltas) if deltas else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_audit" / "live_audit.md",
    )
    args = parser.parse_args()
    rows = parse_live_audit(args.path)
    report = correlate(rows)
    print(f"Audit file: {args.path}")
    print(f"Parsed rows: {report['total_rows']}")
    print(f"entry_proba groups: {report['grouped_with_entry_proba']}")
    print(f"Duplicate-confidence clusters: {report['duplicate_confidence_clusters']}")
    if report.get("step5_to_final_delta_mean") is not None:
        print(
            "step5-to-final delta: "
            f"mean={report['step5_to_final_delta_mean']:.4f} "
            f"min={report['step5_to_final_delta_min']:.4f} "
            f"max={report['step5_to_final_delta_max']:.4f}"
        )
    for c in report.get("clusters", [])[:10]:
        print(
            f"  cluster n={c['count']} conf={c['confidence']:.4f} "
            f"step5={c['step5_samples']} | {c['fingerprint'][:80]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
