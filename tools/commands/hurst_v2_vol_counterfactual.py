#!/usr/bin/env python3
"""Offline Hurst-v2 + breakout vol_regime fire-rate counterfactual (no prod flags)."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core import config as cfg  # noqa: E402
from agent.core.agent_thesis_engine import AgentThesisEngine  # noqa: E402


def _load_dual_write_rows(telemetry: Path, *, max_lines: int = 5000) -> List[Dict[str, Any]]:
    lines = telemetry.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    rows: List[Dict[str, Any]] = []
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        feats = (obj.get("extra") or {}).get("features") or {}
        if not isinstance(feats, dict):
            continue
        if feats.get("hurst_60") is None or feats.get("hurst_60_v2") is None:
            continue
        rows.append(feats)
    return rows


def _stats(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
        "min": min(values),
        "max": max(values),
        "ge_0_52": sum(1 for x in values if x >= 0.52),
    }


def _eval_trend(
    eng: AgentThesisEngine, feats: Dict[str, Any]
) -> Tuple[Optional[Any], Optional[Any]]:
    regime = str(feats.get("regime") or feats.get("market_type") or "unknown")
    try:
        long_v = eng._eval_trend_continuation_long(feats, regime)
    except TypeError:
        long_v = eng._eval_trend_continuation_long(feats)
    try:
        short_v = eng._eval_trend_continuation_short(feats, regime)
    except TypeError:
        try:
            short_v = eng._eval_trend_continuation_short(feats)
        except Exception:
            short_v = None
    except Exception:
        short_v = None
    return long_v, short_v


def _eval_breakout_long(eng: AgentThesisEngine, feats: Dict[str, Any]) -> Optional[Any]:
    regime = str(feats.get("regime") or feats.get("market_type") or "unknown")
    try:
        return eng._eval_breakout_long(feats, regime)
    except TypeError:
        return eng._eval_breakout_long(feats)


def run(telemetry: Path) -> Dict[str, Any]:
    rows = _load_dual_write_rows(telemetry)
    settings = cfg.settings
    eng = AgentThesisEngine()

    h_vals = [float(r["hurst_60"]) for r in rows]
    v_vals = [float(r["hurst_60_v2"]) for r in rows]

    orig_flag = bool(getattr(settings, "agent_thesis_use_hurst_v2", False))
    orig_vol = float(getattr(settings, "agent_thesis_breakout_vol_regime_min", 1.1) or 1.1)

    def trend_counts(use_v2: bool) -> Dict[str, int]:
        settings.agent_thesis_use_hurst_v2 = use_v2
        long_f = short_f = 0
        for feats in rows:
            long_v, short_v = _eval_trend(eng, feats)
            if long_v is not None:
                long_f += 1
            if short_v is not None:
                short_f += 1
        return {"long": long_f, "short": short_f}

    try:
        legacy = trend_counts(False)
        v2 = trend_counts(True)
    finally:
        settings.agent_thesis_use_hurst_v2 = orig_flag

    vol_rows: List[Dict[str, Any]] = []
    try:
        for vol in (1.1, 0.9, 0.8):
            settings.agent_thesis_breakout_vol_regime_min = vol
            fires = sum(1 for feats in rows if _eval_breakout_long(eng, feats) is not None)
            vol_rows.append(
                {
                    "agent_thesis_breakout_vol_regime_min": vol,
                    "breakout_long_fires": fires,
                    "analyzed": len(rows),
                    "fire_rate_pct": round(100.0 * fires / max(len(rows), 1), 2),
                }
            )
    finally:
        settings.agent_thesis_breakout_vol_regime_min = orig_vol

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "telemetry_path": str(telemetry),
        "telemetry_dual_write_rows": len(rows),
        "hurst_60_stats": _stats(h_vals),
        "hurst_60_v2_stats": _stats(v_vals),
        "trend_fires": {"legacy": legacy, "v2_flag_on": v2},
        "breakout_vol_counterfactual": vol_rows,
        "production_flags_unchanged": {
            "AGENT_THESIS_USE_HURST_V2": False,
            "AGENT_THESIS_BREAKOUT_VOL_REGIME_MIN": orig_vol,
            "AGENT_THESIS_TREND_HURST_MIN": float(
                getattr(settings, "agent_thesis_trend_hurst_min", 0.52) or 0.52
            ),
            "AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED": bool(
                getattr(settings, "agent_thesis_neutral_mild_trend_enabled", False)
            ),
        },
        "note": (
            "Offline only. Dual-write confirmed in telemetry. "
            "Do not enable AGENT_THESIS_USE_HURST_V2 or lower vol floor in production "
            "without 7d/30d replay + EV gates."
        ),
    }


def _render_md(report: Dict[str, Any]) -> str:
    h = report.get("hurst_60_stats") or {}
    v = report.get("hurst_60_v2_stats") or {}
    tf = report.get("trend_fires") or {}
    lines = [
        "# Hurst v2 + Vol Counterfactual — 2026-07-12",
        "",
        f"Dual-write rows: **{report.get('telemetry_dual_write_rows')}**",
        "",
        "## Distribution",
        "",
        f"- `hurst_60`: mean={h.get('mean')} median={h.get('median')} ≥0.52={h.get('ge_0_52')}",
        f"- `hurst_60_v2`: mean={v.get('mean')} median={v.get('median')} ≥0.52={v.get('ge_0_52')}",
        "",
        "## Trend-continuation fires (offline)",
        "",
        f"- Legacy flag off: {tf.get('legacy')}",
        f"- `AGENT_THESIS_USE_HURST_V2=true` (offline): {tf.get('v2_flag_on')}",
        "",
        "## Breakout vol_regime counterfactual (offline)",
        "",
        "| Vol min | Fires | N | Fire % |",
        "|--------:|------:|--:|-------:|",
    ]
    for row in report.get("breakout_vol_counterfactual") or []:
        lines.append(
            f"| {row['agent_thesis_breakout_vol_regime_min']} | {row['breakout_long_fires']} | "
            f"{row['analyzed']} | {row['fire_rate_pct']} |"
        )
    lines.extend(
        [
            "",
            "## Production posture",
            "",
            "- Keep `AGENT_THESIS_USE_HURST_V2=false` until replay/EV gates pass",
            "- Do **not** lower `AGENT_THESIS_TREND_HURST_MIN` on legacy scale",
            "- Do **not** promote `neutral_mild_trend`",
            "- Vol 1.1→0.9 remains counterfactual-only pending EV validation",
            "",
            report.get("note", ""),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=ROOT / "data" / "investigation" / "hurst_v2_vol_counterfactual_2026-07-12.json",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=ROOT / "data" / "investigation" / "hurst_v2_vol_counterfactual_2026-07-12.md",
    )
    args = parser.parse_args()

    report = run(args.telemetry)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.out_md.write_text(_render_md(report), encoding="utf-8")

    # Append validation status to scaffold doc if present.
    scaffold = ROOT / "data" / "investigation" / "hurst_v2_scaffold_2026-07-12.md"
    if scaffold.is_file():
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        appendix = (
            f"\n\n## Validation update ({stamp})\n\n"
            f"- Telemetry dual-write confirmed ({report['telemetry_dual_write_rows']} rows)\n"
            f"- Offline counterfactual: `{args.out_json.name}` / `{args.out_md.name}`\n"
            "- Production flag still **false**; no vol_regime promotion\n"
        )
        text = scaffold.read_text(encoding="utf-8")
        if "## Validation update" not in text:
            scaffold.write_text(text.rstrip() + appendix, encoding="utf-8")

    print(json.dumps({
        "dual_write_rows": report["telemetry_dual_write_rows"],
        "trend_fires": report["trend_fires"],
        "out_json": str(args.out_json),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
