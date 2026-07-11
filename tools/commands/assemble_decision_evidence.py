#!/usr/bin/env python3
"""Assemble enriched decision evidence with per-feature provenance."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.signal_recovery.decision_evidence import (  # noqa: E402
    enrich_from_sources,
    provenance_report,
    render_coverage_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=168.0)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Agent log export (default: latest agent_exp_shadow_*.log or docker export)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Default: data/investigation/decision_evidence/<date>/",
    )
    args = parser.parse_args()

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = args.out_dir or (ROOT / "data" / "investigation" / "decision_evidence" / date_tag)
    out_dir.mkdir(parents=True, exist_ok=True)

    log_path = args.log
    if log_path is None:
        inv = ROOT / "data" / "investigation"
        candidates = sorted(inv.glob("agent_exp_shadow_*.log"), reverse=True)
        if not candidates:
            candidates = sorted(inv.glob("agent_baseline_*.log"), reverse=True)
        log_path = candidates[0] if candidates else None

    if log_path is None or not log_path.is_file():
        print("No agent log found; pass --log", file=sys.stderr)
        return 1

    records = enrich_from_sources(
        telemetry_path=args.telemetry,
        log_path=log_path,
        hours=args.hours,
    )
    coverage = provenance_report(records)

    enriched_path = out_dir / "enriched.ndjson"
    with enriched_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.to_dict(), separators=(",", ":")) + "\n")

    coverage_json = {**coverage, "log_path": str(log_path), "telemetry_path": str(args.telemetry)}
    (out_dir / "coverage.json").write_text(json.dumps(coverage_json, indent=2), encoding="utf-8")
    (out_dir / "coverage.md").write_text(render_coverage_markdown(coverage_json), encoding="utf-8")

    print(
        json.dumps(
            {
                "records": len(records),
                "total_b4": coverage.get("total_b4"),
                "high_confidence": coverage.get("high_confidence"),
                "sweep_gate": coverage.get("sweep_gate"),
                "out_dir": str(out_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
