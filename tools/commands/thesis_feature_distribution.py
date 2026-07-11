#!/usr/bin/env python3
"""Feature distribution analysis on high-confidence enriched decision evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.signal_recovery.decision_evidence import (  # noqa: E402
    filter_high_confidence,
    load_enriched_ndjson,
)


def _hurst_bucket(val: float) -> str:
    if val <= 0.0:
        return "0"
    if val < 0.3:
        return "0-0.3"
    if val < 0.52:
        return "0.3-0.52"
    return "0.52+"


def analyze_distributions(records: List[Any]) -> Dict[str, Any]:
    b4 = [r for r in records if r.bucket == "B4"]
    hi = filter_high_confidence(b4)

    hurst_hist = Counter()
    hurst_zero = 0
    adx_below_25 = 0
    vol_below_11 = 0
    co_occur = Counter()

    for rec in hi:
        feats = rec.features
        h = feats.get("hurst_60")
        adx = feats.get("adx_14")
        vol = feats.get("vol_regime")
        if h and h.observed and h.value is not None:
            hurst_hist[_hurst_bucket(float(h.value))] += 1
            if float(h.value) <= 0.0:
                hurst_zero += 1
        if adx and adx.observed and adx.value is not None and float(adx.value) < 25.0:
            adx_below_25 += 1
        if vol and vol.observed and vol.value is not None and float(vol.value) < 1.1:
            vol_below_11 += 1
        if (
            h
            and h.observed
            and h.value is not None
            and float(h.value) < 0.52
            and adx
            and adx.observed
            and adx.value is not None
            and float(adx.value) < 25.0
        ):
            co_occur["hurst_low+adx_low"] += 1

    n = len(hi)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "b4_total": len(b4),
        "high_confidence": n,
        "hurst_histogram": dict(hurst_hist),
        "hurst_zero_count": hurst_zero,
        "hurst_zero_pct": round(hurst_zero / max(n, 1) * 100.0, 2),
        "adx_below_25_count": adx_below_25,
        "adx_below_25_pct": round(adx_below_25 / max(n, 1) * 100.0, 2),
        "vol_below_11_count": vol_below_11,
        "vol_below_11_pct": round(vol_below_11 / max(n, 1) * 100.0, 2),
        "co_occurrence": dict(co_occur),
        "interpretation": (
            "hurst_60=0.0 is a computed clip value, not missing-data default (fillna=0.5 in pipeline)."
        ),
    }


def _render_md(report: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Hurst / Feature Distribution — High-Confidence B4",
            "",
            f"Generated: {report.get('generated_at')}",
            f"High-confidence B4: **{report.get('high_confidence')}** / {report.get('b4_total')}",
            "",
            "## Hurst histogram",
            "",
            "| Bucket | Count |",
            "|--------|------:|",
            *[
                f"| {k} | {v} |"
                for k, v in sorted((report.get("hurst_histogram") or {}).items())
            ],
            "",
            f"- Hurst exactly 0: {report.get('hurst_zero_count')} ({report.get('hurst_zero_pct')}%)",
            f"- ADX < 25: {report.get('adx_below_25_count')} ({report.get('adx_below_25_pct')}%)",
            f"- Vol regime < 1.1: {report.get('vol_below_11_count')} ({report.get('vol_below_11_pct')}%)",
            "",
            "## Co-occurrence",
            "",
            *[f"- {k}: {v}" for k, v in (report.get("co_occurrence") or {}).items()],
            "",
            report.get("interpretation", ""),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args()

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_json = args.out_json or (
        ROOT / "data" / "investigation" / f"hurst_distribution_{date_tag}.json"
    )
    out_md = args.out_md or (
        ROOT / "data" / "investigation" / f"hurst_distribution_{date_tag}.md"
    )

    records = load_enriched_ndjson(args.evidence_json)
    report = analyze_distributions(records)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out_md.write_text(_render_md(report), encoding="utf-8")
    print(json.dumps({"high_confidence": report["high_confidence"], "out_md": str(out_md)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
