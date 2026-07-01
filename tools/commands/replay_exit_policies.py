#!/usr/bin/env python3
"""Replay exit policies on closed trade history."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _fetch_trades(start: str, end: str) -> List[Dict[str, Any]]:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return []
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(_normalize_psycopg_url(url))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT pnl, close_reason, metadata
                FROM trade_outcomes
                WHERE closed_at::date BETWEEN %s AND %s
                ORDER BY closed_at
                """,
                (start, end),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _policy_bracket(row: Dict[str, Any]) -> Dict[str, Any]:
    """Actual bracket outcome baseline."""
    return {
        "policy": "bracket_actual",
        "pnl": float(row.get("pnl") or 0),
        "exit_reason": row.get("close_reason"),
    }


def _policy_tle_log_only(row: Dict[str, Any]) -> Dict[str, Any]:
    """Counterfactual: would log-only TLE EXIT have fired earlier?"""
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    monitoring = meta.get("position_monitoring")
    if not isinstance(monitoring, list):
        return {"policy": "tle_log_only", "pnl": float(row.get("pnl") or 0), "note": "no_monitoring"}
    for rec in monitoring:
        if str(rec.get("action_would_be")) == "EXIT":
            return {
                "policy": "tle_log_only",
                "would_exit_at_bar": rec.get("bar_index"),
                "health_score": rec.get("health_score"),
                "pnl_actual": float(row.get("pnl") or 0),
            }
    return {"policy": "tle_log_only", "pnl": float(row.get("pnl") or 0), "note": "no_exit_signal"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay exit policies on trade history")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trades = _fetch_trades(args.start, args.end)
    results = []
    for row in trades:
        results.append(
            {
                "bracket": _policy_bracket(row),
                "tle_log_only": _policy_tle_log_only(row),
            }
        )

    out = {
        "window": {"start": args.start, "end": args.end},
        "trade_count": len(trades),
        "policies": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {len(results)} trade replays to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
