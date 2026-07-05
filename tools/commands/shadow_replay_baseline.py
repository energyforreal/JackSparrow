#!/usr/bin/env python3
"""Phase 1b: orchestrate historical shadow replay and write baseline JSON."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
for candidate in Path(__file__).resolve().parents:
    if (candidate / "agent").is_dir() and (candidate / "backend").is_dir():
        ROOT = candidate
        break
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "data" / "investigation" / "shadow_replay_baseline.json"


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _connect():
    import psycopg2

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    return psycopg2.connect(_normalize_psycopg_url(url))


def _trade_window() -> Tuple[str, str, int]:
    conn = _connect()
    if conn is None:
        return "2026-01-01", datetime.now(timezone.utc).date().isoformat(), 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MIN(closed_at::date)::text, MAX(closed_at::date)::text, COUNT(*)
                FROM trade_outcomes
                """
            )
            row = cur.fetchone()
            start, end, count = row[0], row[1], int(row[2] or 0)
            if not start or not end:
                today = datetime.now(timezone.utc).date().isoformat()
                return today, today, 0
            return start, end, count
    finally:
        conn.close()


def _gross_pnl_from_row(row: Dict[str, Any]) -> Optional[float]:
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    outcome = meta.get("outcome") if isinstance(meta.get("outcome"), dict) else {}
    for key in ("gross_pnl_usd", "gross_pnl"):
        if outcome.get(key) is not None:
            try:
                return float(outcome[key])
            except (TypeError, ValueError):
                pass
        if meta.get(key) is not None:
            try:
                return float(meta[key])
            except (TypeError, ValueError):
                pass
    return None


def _economic_summary(start: str, end: str) -> Dict[str, Any]:
    from tools.commands.trade_analytics import _connect as ta_connect

    conn = ta_connect()
    if conn is None:
        return {"error": "no_db"}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pnl, metadata, close_reason
                FROM trade_outcomes
                WHERE closed_at::date BETWEEN %s AND %s
                ORDER BY closed_at
                """,
                (start, end),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    trades = []
    fee_dominated = 0
    for pnl, meta, reason in rows:
        p = float(pnl or 0)
        row = {"pnl": p, "metadata": meta, "close_reason": reason}
        g_f = _gross_pnl_from_row(row)
        if g_f is not None and g_f > 0 and p <= 0:
            fee_dominated += 1
        trades.append(row)

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
    pf = sum(wins) / sum(losses) if losses else (999.0 if wins else 0.0)
    exp = sum(t["pnl"] for t in trades) / len(trades) if trades else 0.0
    return {
        "trade_count": len(trades),
        "expectancy_usd": round(exp, 4),
        "profit_factor": round(pf, 4),
        "fee_dominated_count": fee_dominated,
        "fee_dominated_rate": round(fee_dominated / len(trades), 4) if trades else 0.0,
        "win_rate": round(len(wins) / len(trades), 4) if trades else 0.0,
        "avg_win_usd": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss_usd": round(sum(losses) / len(losses), 4) if losses else 0.0,
    }


def _regime_breakdown(start: str, end: str) -> Dict[str, Any]:
    conn = _connect()
    if conn is None:
        return {}
    buckets: Dict[str, List[float]] = {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pnl, metadata
                FROM trade_outcomes
                WHERE closed_at::date BETWEEN %s AND %s
                """,
                (start, end),
            )
            for pnl, meta in cur.fetchall():
                regime = "unknown"
                if isinstance(meta, dict):
                    dc = meta.get("decision_context") or {}
                    rb = dc.get("rule_based_pipeline") or {}
                    ms = rb.get("market_state") or {}
                    regime = str(
                        ms.get("regime")
                        or dc.get("regime_benchmark")
                        or meta.get("regime_benchmark")
                        or "unknown"
                    )
                buckets.setdefault(regime, []).append(float(pnl or 0))
    finally:
        conn.close()

    out: Dict[str, Any] = {}
    for regime, pnls in buckets.items():
        wins = sum(p for p in pnls if p > 0)
        losses = sum(abs(p) for p in pnls if p < 0)
        out[regime] = {
            "trade_count": len(pnls),
            "expectancy_usd": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
            "profit_factor": round(wins / losses, 4) if losses else (999.0 if wins else 0.0),
        }
    return out


def _run_subcommand(script: str, args: List[str]) -> int:
    cmd = [sys.executable, str(ROOT / "tools" / "commands" / script), *args]
    print(f">>> {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="Directory for replay sub-artifacts (default: same dir as --out)",
    )
    parser.add_argument("--skip-replay", action="store_true")
    args = parser.parse_args()

    auto_start, auto_end, total = _trade_window()
    start = args.start or auto_start
    end = args.end or auto_end

    inv = Path(args.artifact_dir) if args.artifact_dir else Path(args.out).parent
    inv.mkdir(parents=True, exist_ok=True)
    replay_exit_out = inv / f"replay_exit_{start}_{end}.json"
    replay_exc_out = inv / f"replay_excursions_{start}_{end}.json"
    tle_out = ROOT / "data" / "experiments" / "tle_agreement_latest.json"
    if args.artifact_dir:
        tle_out = inv / "tle_agreement_latest.json"

    if not args.skip_replay:
        _run_subcommand(
            "replay_exit_policies.py",
            ["--start", start, "--end", end, "--out", str(replay_exit_out)],
        )
        _run_subcommand(
            "replay_trade_excursions.py",
            ["--start", start, "--end", end, "--out", str(replay_exc_out)],
        )
        _run_subcommand(
            "tle_agreement_score.py",
            ["--start", start, "--end", end, "--out", str(tle_out)],
        )

    baseline = {
        "phase": "1b_shadow_replay_baseline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start, "end": end, "total_trades_in_db": total},
        "actual_cohort": _economic_summary(start, end),
        "per_regime": _regime_breakdown(start, end),
        "artifacts": {
            "replay_exit_policies": str(replay_exit_out),
            "replay_trade_excursions": str(replay_exc_out),
            "tle_agreement": str(tle_out),
        },
        "rule": "No Phase 3 .env change without matching improvement on this window.",
    }

    for key, path in baseline["artifacts"].items():
        p = Path(path)
        if p.is_file():
            try:
                baseline[f"{key}_summary"] = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                baseline[f"{key}_summary"] = {"error": "invalid_json"}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(baseline, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
