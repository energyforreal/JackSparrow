#!/usr/bin/env python3
"""Replay market context to test signal robustness on historical trades."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

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
                SELECT signal, side, metadata
                FROM trade_outcomes
                WHERE closed_at::date BETWEEN %s AND %s
                ORDER BY closed_at
                """,
                (start, end),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _signal_robustness(row: Dict[str, Any]) -> Dict[str, Any]:
    from agent.persistence.trade_snapshot import reconstruct_market_context_from_snapshot

    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    mc = reconstruct_market_context_from_snapshot(meta)
    rb = mc.get("rule_based_pipeline") if isinstance(mc.get("rule_based_pipeline"), dict) else {}
    fsm = rb.get("fsm_decision") if isinstance(rb.get("fsm_decision"), dict) else {}
    gates = rb.get("structural_gates") if isinstance(rb.get("structural_gates"), dict) else {}

    entry_signal = str(fsm.get("entry_signal") or "HOLD")
    trade_allowed = bool(gates.get("trade_allowed"))
    original_signal = str(row.get("signal") or row.get("side") or "")

    would_fire = entry_signal not in ("HOLD", "") and trade_allowed
    score = 1.0 if would_fire else 0.0
    if would_fire and original_signal:
        orig_long = original_signal.upper() in ("LONG", "BUY", "STRONG_LONG", "STRONG_BUY")
        orig_short = original_signal.upper() in ("SHORT", "SELL", "STRONG_SHORT", "STRONG_SELL")
        replay_long = entry_signal.upper() in ("LONG", "BUY", "STRONG_LONG", "STRONG_BUY")
        replay_short = entry_signal.upper() in ("SHORT", "SELL", "STRONG_SHORT", "STRONG_SELL")
        if (orig_long and replay_long) or (orig_short and replay_short):
            score = 1.0
        elif orig_long or orig_short:
            score = 0.5

    return {
        "original_signal": original_signal,
        "replayed_entry_signal": entry_signal,
        "trade_allowed": trade_allowed,
        "signal_robustness_score": score,
        "would_signal_fire": would_fire,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Market context signal replay")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trades = _fetch_trades(args.start, args.end)
    results = [_signal_robustness(t) for t in trades]
    robust = [r["signal_robustness_score"] for r in results]
    summary = {
        "window": {"start": args.start, "end": args.end},
        "trade_count": len(trades),
        "mean_robustness": sum(robust) / len(robust) if robust else 0.0,
        "trades": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"trade_count": len(trades), "mean_robustness": summary["mean_robustness"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
