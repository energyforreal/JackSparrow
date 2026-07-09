#!/usr/bin/env python3
"""Label rejected entry_decisions with forward market outcomes (false negatives)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _connect():
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 required", file=sys.stderr)
        return None
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("Set DATABASE_URL", file=sys.stderr)
        return None
    try:
        return psycopg2.connect(_normalize_psycopg_url(url))
    except Exception as exc:
        print(f"DB connection failed: {exc}", file=sys.stderr)
        return None


def _fetch_unlabeled_rejects(conn, limit: int) -> List[Dict[str, Any]]:
    from psycopg2.extras import RealDictCursor

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT ed.decision_id, ed.symbol, ed.timestamp, ed.signal, ed.side,
                   ed.metadata
            FROM entry_decisions ed
            LEFT JOIN entry_decision_labels el ON ed.decision_id = el.decision_id
            WHERE ed.outcome = 'rejected' AND el.decision_id IS NULL
            ORDER BY ed.timestamp ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def reference_price_from_metadata(meta: Dict[str, Any]) -> Optional[float]:
    """Resolve entry reference price from enriched reject snapshot metadata."""
    dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
    features = dc.get("features") if isinstance(dc.get("features"), dict) else {}
    ref_price = features.get("close") or dc.get("current_price")
    if ref_price is None:
        return None
    try:
        px = float(ref_price)
    except (TypeError, ValueError):
        return None
    return px if px > 0 else None


async def _label_one(
    row: Dict[str, Any],
    *,
    horizon_bars: int,
    bar_minutes: int = 5,
) -> Optional[Dict[str, Any]]:
    from agent.persistence.trade_excursions import compute_excursions, price_delta_excursions

    symbol = str(row.get("symbol") or "BTCUSD")
    ts = row.get("timestamp")
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    entry_price = reference_price_from_metadata(meta)
    if entry_price is None:
        return None

    start_ts = int(ts.timestamp())
    end_ts = int((ts + timedelta(minutes=horizon_bars * bar_minutes)).timestamp())

    side = str(row.get("side") or row.get("signal") or "long").lower()
    is_long = side in ("long", "buy")

    try:
        from agent.data.delta_client import DeltaExchangeClient

        client = DeltaExchangeClient()
        resp = await client.get_candles(
            symbol=symbol,
            resolution=f"{bar_minutes}m",
            start=start_ts,
            end=end_ts,
        )
        result = resp.get("result") if isinstance(resp, dict) else None
        candles: List[Dict[str, Any]] = []
        if isinstance(result, list):
            candles = result
        elif isinstance(result, dict) and isinstance(result.get("candles"), list):
            candles = result["candles"]
    except Exception:
        candles = []

    if candles:
        last_close = float(candles[-1].get("close") or entry_price)
        exc = compute_excursions(
            side=side,
            entry_price=entry_price,
            candles=candles,
            sl=None,
            tp=None,
        )
        forward_return_pct = (
            (last_close - entry_price) / entry_price * 100.0
            if is_long
            else (entry_price - last_close) / entry_price * 100.0
        )
    else:
        exc = price_delta_excursions(
            side=side, entry_price=entry_price, exit_price=entry_price
        )
        forward_return_pct = 0.0

    would_have_won = forward_return_pct > 0
    return {
        "decision_id": str(row["decision_id"]),
        "label_horizon_bars": horizon_bars,
        "forward_return_pct": round(forward_return_pct, 4),
        "forward_mfe_pct": exc.get("mfe_pct"),
        "forward_mae_pct": exc.get("mae_pct"),
        "would_have_won": would_have_won,
    }


async def run_labeling(*, limit: int, horizon_bars: int) -> int:
    conn = _connect()
    if conn is None:
        return 2
    try:
        rows = _fetch_unlabeled_rejects(conn, limit)
        if not rows:
            print("No unlabeled rejects found.")
            return 0
        labeled = 0
        for row in rows:
            ts = row.get("timestamp")
            if isinstance(ts, datetime):
                age = datetime.now(timezone.utc) - (
                    ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                )
                if age < timedelta(minutes=horizon_bars * 5):
                    continue
            result = await _label_one(row, horizon_bars=horizon_bars)
            if not result:
                continue
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO entry_decision_labels (
                        decision_id, label_horizon_bars, forward_return_pct,
                        forward_mfe_pct, forward_mae_pct, would_have_won, labeled_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (decision_id) DO NOTHING
                    """,
                    (
                        result["decision_id"],
                        result["label_horizon_bars"],
                        result["forward_return_pct"],
                        result["forward_mfe_pct"],
                        result["forward_mae_pct"],
                        result["would_have_won"],
                    ),
                )
            conn.commit()
            labeled += 1
        print(f"Labeled {labeled} rejected entry decisions.")
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Label rejected entry decisions")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--horizon-bars", type=int, default=12)
    args = parser.parse_args()
    return asyncio.run(run_labeling(limit=args.limit, horizon_bars=args.horizon_bars))


if __name__ == "__main__":
    raise SystemExit(main())
