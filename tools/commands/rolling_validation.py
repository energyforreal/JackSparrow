#!/usr/bin/env python3
"""Daily rolling validation: 7d/30d counterfactual replay archived by date."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.commands.counterfactual_replay import (  # noqa: E402
    _render_markdown,
    run_replay,
)
from tools.commands.decision_quality_index import compute_dqi  # noqa: E402
from scripts.signal_recovery.log_parser import filter_since, load_telemetry  # noqa: E402

BASELINE_COMMIT = "0503847"
BASELINE_POLICY = "hold_baseline_policy"
DEFAULT_WINDOWS = (168.0, 720.0)  # 7d, 30d


def _policy_hold_pct(report: Dict[str, Any]) -> float | None:
    table = report.get("scenario_table") or {}
    current = table.get("current") or {}
    ml_only = table.get("ml_only") or {}
    ml_trades = int(ml_only.get("trades") or 0)
    current_trades = int(current.get("trades") or 0)
    if ml_trades <= 0:
        return None
    return round((1.0 - current_trades / ml_trades) * 100.0, 1)


def _regime_summary(by_regime: Dict[str, Any]) -> List[str]:
    lines = [
        "| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |",
        "|--------|-------------:|-------------:|-------------------:|",
    ]
    for regime, scenarios in sorted((by_regime or {}).items()):
        cur = (scenarios.get("current") or {}).get("ev_pct")
        ml = (scenarios.get("ml_only") or {}).get("ev_pct")
        flat = (scenarios.get("ml_adopt_flat") or {}).get("ev_pct")
        lines.append(f"| {regime} | {cur} | {ml} | {flat} |")
    return lines


def _render_dashboard(
    *,
    stamp: str,
    reports: Dict[str, Dict[str, Any]],
) -> str:
    lines = [
        "# Rolling Validation Dashboard",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Archive date: {stamp}",
        f"Baseline commit: `{BASELINE_COMMIT}`",
        f"Baseline policy: `{BASELINE_POLICY}`",
        "",
        "## Weekly metrics",
        "",
        "| Window | Candidates | Policy HOLD % | current trades | ml_only EV % | Recommendation |",
        "|--------|------------|---------------|----------------|--------------|----------------|",
    ]
    for label, report in reports.items():
        hold_pct = _policy_hold_pct(report)
        table = report.get("scenario_table") or {}
        current = table.get("current") or {}
        ml_only = table.get("ml_only") or {}
        promo = report.get("promotion_gates") or {}
        lines.append(
            f"| {label} | {report.get('labeled_count')} | {hold_pct} | "
            f"{current.get('trades')} | {ml_only.get('ev_pct')} | "
            f"{promo.get('recommendation')} |"
        )

    for label, report in reports.items():
        lines.extend(["", f"## Regime breakdown ({label})", ""])
        lines.extend(_regime_summary(report.get("by_regime") or {}))

    lines.extend(
        [
            "",
            "## Governance",
            "",
            "Policy change requires: rolling replay positive EV, forward shadow G6 pass,",
            "regime-stratified validation, and documented approval against baseline.",
            "",
            "See `data/investigation/investigation_closure_2026-07-11.md`.",
        ]
    )
    return "\n".join(lines)


async def run_rolling(
    *,
    telemetry_path: Path,
    out_dir: Path,
    windows: tuple[float, ...],
    horizon_bars: int,
    bar_minutes: int,
    economic: bool,
    concurrency: int,
) -> Dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive = out_dir / stamp
    archive.mkdir(parents=True, exist_ok=True)

    reports: Dict[str, Dict[str, Any]] = {}
    for hours in windows:
        label = f"{int(hours)}h"
        report = await run_replay(
            telemetry_path=telemetry_path,
            hours=hours,
            horizon_bars=horizon_bars,
            bar_minutes=bar_minutes,
            economic=economic,
            concurrency=concurrency,
        )
        candidates = report.pop("candidates", [])
        json_path = archive / f"counterfactual_replay_{label}.json"
        md_path = archive / f"counterfactual_replay_{label}.md"
        full = {**report, "candidates": candidates}
        json_path.write_text(json.dumps(full, indent=2, default=str), encoding="utf-8")
        md_path.write_text(_render_markdown(report), encoding="utf-8")
        reports[label] = report

    dashboard = _render_dashboard(stamp=stamp, reports=reports)
    try:
        rows = filter_since(load_telemetry(telemetry_path), max(windows))
        dqi = compute_dqi(replay_report=reports.get(f"{int(max(windows))}h"), telemetry_rows=rows)
        dashboard += (
            f"\n\n## Decision Quality Index\n\n"
            f"Composite DQI: **{dqi.get('composite_dqi')}** "
            f"(weight coverage {dqi.get('weight_coverage')})\n"
        )
        (archive / f"dqi_{stamp}.json").write_text(
            json.dumps(dqi, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        dashboard += f"\n\n## Decision Quality Index\n\nDQI unavailable: {exc}\n"

    dash_path = archive / "dashboard.md"
    dash_path.write_text(dashboard, encoding="utf-8")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "archive_dir": str(archive),
        "baseline_commit": BASELINE_COMMIT,
        "baseline_policy": BASELINE_POLICY,
        "windows": {k: v.get("scenario_table") for k, v in reports.items()},
        "promotion": {k: v.get("promotion_gates") for k, v in reports.items()},
    }
    (archive / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "data" / "investigation" / "rolling",
    )
    parser.add_argument(
        "--windows",
        type=float,
        nargs="+",
        default=list(DEFAULT_WINDOWS),
        help="Replay window lengths in hours (default: 168 720 = 7d 30d)",
    )
    parser.add_argument("--horizon-bars", type=int, default=2)
    parser.add_argument("--bar-minutes", type=int, default=5)
    parser.add_argument("--economic", action="store_true", default=True)
    parser.add_argument("--no-economic", action="store_false", dest="economic")
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    summary = asyncio.run(
        run_rolling(
            telemetry_path=args.telemetry,
            out_dir=args.out_dir,
            windows=tuple(args.windows),
            horizon_bars=args.horizon_bars,
            bar_minutes=args.bar_minutes,
            economic=args.economic,
            concurrency=args.concurrency,
        )
    )
    print(json.dumps(summary, indent=2))
    print(f"Wrote dashboard to {summary['archive_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
