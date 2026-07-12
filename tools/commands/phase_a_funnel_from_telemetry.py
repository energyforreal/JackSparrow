#!/usr/bin/env python3
"""Phase A layered funnel from decision telemetry (read-only).

Counts thesis fires vs quality-floor / Gate5 / HOLD outcomes so scorecards
separate opportunity generation from entry admission.

Examples::

    python tools/commands/phase_a_funnel_from_telemetry.py --hours 24 \\
      --out data/investigation/deselectivity/2026-07-12/funnel_day1

    python tools/commands/phase_a_funnel_from_telemetry.py \\
      --since 2026-07-12T10:21:37+00:00 --out .../funnel_post_a
"""

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


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _codes(row: Dict[str, Any]) -> List[str]:
    return [str(c) for c in (row.get("policy_reason_codes") or [])]


def _code_map(codes: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for c in codes:
        if "=" in c:
            k, v = c.split("=", 1)
            out[k.lower()] = v
        else:
            out[c.lower()] = "1"
    return out


def _thesis_type(codes: List[str], cmap: Dict[str, str]) -> str:
    if "thesis_type" in cmap:
        return cmap["thesis_type"].lower()
    for c in codes:
        if c.startswith("thesis_type="):
            return c.split("=", 1)[1].lower()
    return "unknown"


def _is_entry_thesis(thesis_signal: str) -> bool:
    return str(thesis_signal or "HOLD").upper() in ("LONG", "SHORT", "BUY", "SELL")


def analyze_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n_pred = 0
    thesis_fires = 0
    thesis_by_type: Counter[str] = Counter()
    thesis_by_side: Counter[str] = Counter()
    quality_below = 0
    gate5_fail = 0
    hold_after_thesis = 0
    risk_veto = 0
    dual_write = 0
    dual_write_eligible = 0
    quality_scores: List[float] = []

    for row in rows:
        if str(row.get("event") or "") != "v43_prediction_complete":
            continue
        n_pred += 1
        codes = _codes(row)
        cmap = _code_map(codes)
        feats = (row.get("extra") or {}).get("features") or {}
        if isinstance(feats, dict) and feats:
            dual_write_eligible += 1
            if feats.get("hurst_60") is not None and feats.get("hurst_60_v2") is not None:
                dual_write += 1

        ttype = _thesis_type(codes, cmap)
        thesis_sig = str(row.get("thesis_signal") or (row.get("signals") or {}).get("thesis") or "HOLD")
        policy_sig = str(row.get("signal") or (row.get("signals") or {}).get("policy") or "HOLD")

        fired = _is_entry_thesis(thesis_sig) and ttype in (
            "trend_continuation",
            "breakout",
            "mean_reversion",
            "neutral_mild_trend",
        )
        # Also count when reason codes show thesis entry even if type parsing misses
        if not fired and any(
            c.startswith("thesis_trend_continuation")
            or c.startswith("thesis_breakout")
            or c == "agent_thesis_entry"
            for c in codes
        ):
            fired = _is_entry_thesis(thesis_sig)

        if fired:
            thesis_fires += 1
            thesis_by_type[ttype] += 1
            thesis_by_side[thesis_sig.upper()] += 1
            if policy_sig.upper() == "HOLD":
                hold_after_thesis += 1

        if "quality_below_floor" in cmap or any(c.startswith("quality_below") for c in codes):
            quality_below += 1
            qs = cmap.get("quality_score")
            if qs is not None:
                try:
                    quality_scores.append(float(qs))
                except ValueError:
                    pass

        gates = row.get("gates") if isinstance(row.get("gates"), dict) else {}
        g5 = gates.get("g5_pass")
        if g5 is False or "quality_economic_gate5_fail" in cmap:
            gate5_fail += 1

        if any("risk" in c and "veto" in c for c in codes) or "risk_veto" in cmap:
            risk_veto += 1

    hours = None
    if rows:
        ts_list = [_parse_ts(r.get("ts")) for r in rows]
        ts_list = [t for t in ts_list if t is not None]
        if len(ts_list) >= 2:
            hours = round((max(ts_list) - min(ts_list)).total_seconds() / 3600.0, 2)

    fires_per_24h = None
    if hours and hours > 0:
        fires_per_24h = round(thesis_fires * (24.0 / hours), 2)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_v43_prediction_complete": n_pred,
        "window_hours_approx": hours,
        "thesis_fires": thesis_fires,
        "thesis_fires_per_24h": fires_per_24h,
        "thesis_by_type": dict(thesis_by_type),
        "thesis_by_side": dict(thesis_by_side),
        "quality_below_floor": quality_below,
        "gate5_fail": gate5_fail,
        "hold_after_thesis_fire": hold_after_thesis,
        "risk_veto_like": risk_veto,
        "dual_write_eligible": dual_write_eligible,
        "dual_write_both_hurst": dual_write,
        "dual_write_rate_pct": round(100.0 * dual_write / max(dual_write_eligible, 1), 1),
        "quality_score_mean": round(sum(quality_scores) / len(quality_scores), 2)
        if quality_scores
        else None,
        "promote_fire_gate": {
            "need_ge_5_per_24h_or_2x_baseline": True,
            "fires_per_24h": fires_per_24h,
            "status": (
                "PASS"
                if fires_per_24h is not None and fires_per_24h >= 5
                else "PENDING"
                if thesis_fires > 0
                else "FAIL_OR_INSUFFICIENT"
            ),
        },
    }


def load_telemetry(
    path: Path,
    *,
    hours: Optional[float],
    since: Optional[datetime],
) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    cutoff: Optional[datetime] = since
    if cutoff is None and hours is not None and hours > 0:
        cutoff = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - hours * 3600.0, tz=timezone.utc
        )
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            ts = _parse_ts(obj.get("ts"))
            if cutoff is not None and (ts is None or ts < cutoff):
                continue
            rows.append(obj)
    return rows


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Phase A Funnel (telemetry)",
        "",
        f"Generated: {report.get('generated_at')}",
        f"v43_prediction_complete: {report.get('n_v43_prediction_complete')} | "
        f"window≈{report.get('window_hours_approx')}h",
        "",
        "## Funnel layers",
        "",
        "| Layer | Count |",
        "|-------|------:|",
        f"| Thesis fires (entry thesis) | {report.get('thesis_fires')} |",
        f"| Thesis fires / 24h | {report.get('thesis_fires_per_24h')} |",
        f"| Quality below floor | {report.get('quality_below_floor')} |",
        f"| Gate5 fail | {report.get('gate5_fail')} |",
        f"| HOLD after thesis fire | {report.get('hold_after_thesis_fire')} |",
        f"| Risk veto-like | {report.get('risk_veto_like')} |",
        "",
        "## Thesis mix",
        "",
        f"- by type: `{report.get('thesis_by_type')}`",
        f"- by side: `{report.get('thesis_by_side')}`",
        "",
        "## Dual-write",
        "",
        f"- both hurst fields: {report.get('dual_write_both_hurst')} / "
        f"{report.get('dual_write_eligible')} ({report.get('dual_write_rate_pct')}%)",
        "",
        "## Promote fire gate",
        "",
        f"- status: **{(report.get('promote_fire_gate') or {}).get('status')}** "
        f"(fires/24h={(report.get('promote_fire_gate') or {}).get('fires_per_24h')})",
        "",
        "Read-only. Does not change production flags.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument("--hours", type=float, default=None)
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="ISO timestamp; overrides --hours when set",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "investigation" / "phase_a_funnel",
    )
    args = parser.parse_args()

    since_dt = _parse_ts(args.since) if args.since else None
    hours = args.hours if since_dt is None else None
    if hours is None and since_dt is None:
        hours = 24.0

    rows = load_telemetry(args.telemetry, hours=hours, since=since_dt)
    report = analyze_rows(rows)
    report["telemetry_path"] = str(args.telemetry)
    report["since"] = args.since
    report["hours"] = hours

    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    json_path = Path(str(out) + ".json") if out.suffix == "" else out.with_suffix(".json")
    md_path = Path(str(out) + ".md") if out.suffix == "" else out.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path), "summary": {
        "thesis_fires": report["thesis_fires"],
        "quality_below_floor": report["quality_below_floor"],
        "gate5_fail": report["gate5_fail"],
        "hold_after_thesis_fire": report["hold_after_thesis_fire"],
        "fires_per_24h": report["thesis_fires_per_24h"],
    }}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
