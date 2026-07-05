#!/usr/bin/env python3
"""Shadow replay a single config knob change against historical trade cohort."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
for candidate in Path(__file__).resolve().parents:
    if (candidate / "agent").is_dir() and (candidate / "backend").is_dir():
        ROOT = candidate
        break
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _fetch_trades(start: Optional[str], end: Optional[str]) -> List[Dict[str, Any]]:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return []
    import psycopg2
    from psycopg2.extras import RealDictCursor

    clauses: List[str] = []
    params: List[Any] = []
    if start:
        clauses.append("closed_at::date >= %s")
        params.append(start)
    if end:
        clauses.append("closed_at::date <= %s")
        params.append(end)
    where = (" AND " + " AND ".join(clauses)) if clauses else ""

    conn = psycopg2.connect(_normalize_psycopg_url(url))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT pnl, metadata, close_reason, entry_price, exit_price, side
                FROM trade_outcomes
                WHERE 1=1 {where}
                ORDER BY closed_at
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _round_trip_cost_pct() -> float:
    from agent.core.v43_signal_gates import round_trip_cost_pct

    return round_trip_cost_pct()


def _simulate_entry_economic_veto(
    trades: List[Dict[str, Any]],
    *,
    multiplier: float,
) -> Dict[str, Any]:
    """Counterfactual: block trades whose expected move < multiplier × fees."""
    min_edge = _round_trip_cost_pct() * multiplier
    kept: List[float] = []
    blocked = 0
    for row in trades:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        dc = meta.get("decision_context") or {}
        ml = dc.get("ml_validation") or {}
        expected = abs(float(ml.get("expected_return") or 0.0))
        if expected < min_edge:
            blocked += 1
            continue
        kept.append(float(row.get("pnl") or 0))
    wins = [p for p in kept if p > 0]
    losses = [abs(p) for p in kept if p < 0]
    pf = sum(wins) / sum(losses) if losses else (999.0 if wins else 0.0)
    return {
        "knob": "ENTRY_ECONOMIC_HARD_VETO",
        "multiplier": multiplier,
        "min_edge_pct": min_edge,
        "blocked_trades": blocked,
        "kept_trades": len(kept),
        "counterfactual_expectancy": round(sum(kept) / len(kept), 4) if kept else 0.0,
        "counterfactual_profit_factor": round(pf, 4),
    }


def _simulate_trailing_activation(
    trades: List[Dict[str, Any]],
    *,
    activation_pct: float,
) -> Dict[str, Any]:
    """Heuristic: fee-dominated exits that had positive gross below activation threshold."""
    would_defer = 0
    for row in trades:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        outcome = meta.get("outcome") if isinstance(meta.get("outcome"), dict) else {}
        gross = outcome.get("gross_pnl_usd") or meta.get("gross_pnl_usd")
        pnl = float(row.get("pnl") or 0)
        try:
            g = float(gross) if gross is not None else None
        except (TypeError, ValueError):
            g = None
        if g is None or g <= 0:
            continue
        entry = float(row.get("entry_price") or 0)
        exit_p = float(row.get("exit_price") or 0)
        if entry <= 0:
            continue
        move = abs(exit_p - entry) / entry
        if move < activation_pct and pnl <= 0 and str(row.get("close_reason") or "").startswith(
            "stop"
        ):
            would_defer += 1
    return {
        "knob": "TRAILING_STOP_ACTIVATION_PROFIT_PCT",
        "activation_pct": activation_pct,
        "fee_dominated_trail_exits_heuristic": would_defer,
        "note": "Requires excursion replay for precise counterfactual PnL.",
    }


KNOB_SIMULATORS = {
    "entry_economic_veto": _simulate_entry_economic_veto,
    "trailing_activation": _simulate_trailing_activation,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--knob",
        required=True,
        choices=sorted(KNOB_SIMULATORS.keys()),
    )
    parser.add_argument("--value", type=float, required=True)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "investigation" / "config_shadow_replay.json"),
    )
    args = parser.parse_args()

    trades = _fetch_trades(args.start, args.end)
    sim = KNOB_SIMULATORS[args.knob]
    if args.knob == "entry_economic_veto":
        result = sim(trades, multiplier=args.value)
    else:
        result = sim(trades, activation_pct=args.value)
    result["trade_count"] = len(trades)
    result["window"] = {"start": args.start, "end": args.end}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
