#!/usr/bin/env python3
"""Replay MFE/MAE and TP/SL counterfactuals for closed trades."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
                SELECT closed_at, opened_at, symbol, side, entry_price, exit_price,
                       quantity, pnl, close_reason, metadata
                FROM trade_outcomes
                WHERE closed_at::date BETWEEN %s AND %s
                ORDER BY closed_at
                """,
                (start, end),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _sl_tp_from_meta(meta: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    summary = meta.get("entry_state_summary") if isinstance(meta.get("entry_state_summary"), dict) else {}
    sl = summary.get("stop_loss_at_entry")
    tp = summary.get("take_profit_at_entry")
    if sl is None or tp is None:
        dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
        sl = sl or dc.get("stop_loss_at_entry")
        tp = tp or dc.get("take_profit_at_entry")
    try:
        return (float(sl) if sl is not None else None, float(tp) if tp is not None else None)
    except (TypeError, ValueError):
        return None, None


def _compute_excursions(
    *,
    side: str,
    entry_price: float,
    candles: List[Dict[str, Any]],
    sl: Optional[float],
    tp: Optional[float],
) -> Dict[str, Any]:
    is_long = str(side).lower() in ("long", "buy")
    mfe = 0.0
    mae = 0.0
    mfe_bar = 0
    mae_bar = 0
    bars_until_tp: Optional[int] = None
    bars_until_sl: Optional[int] = None

    for i, c in enumerate(candles):
        high = float(c.get("high") or c.get("close") or entry_price)
        low = float(c.get("low") or c.get("close") or entry_price)
        if is_long:
            fav = high - entry_price
            adv = entry_price - low
            hit_tp = tp is not None and high >= tp
            hit_sl = sl is not None and low <= sl
        else:
            fav = entry_price - low
            adv = high - entry_price
            hit_tp = tp is not None and low <= tp
            hit_sl = sl is not None and high >= sl
        if fav > mfe:
            mfe = fav
            mfe_bar = i + 1
        if adv > mae:
            mae = adv
            mae_bar = i + 1
        if bars_until_tp is None and hit_tp:
            bars_until_tp = i + 1
        if bars_until_sl is None and hit_sl:
            bars_until_sl = i + 1

    return {
        "bars_held": len(candles),
        "mfe_usd": round(mfe, 2),
        "mae_usd": round(mae, 2),
        "mfe_pct": round(mfe / entry_price * 100, 4) if entry_price else 0,
        "mae_pct": round(mae / entry_price * 100, 4) if entry_price else 0,
        "time_to_mfe_bars": mfe_bar,
        "time_to_mae_bars": mae_bar,
        "bars_until_tp": bars_until_tp,
        "bars_until_sl": bars_until_sl,
        "tp_would_hit": bars_until_tp is not None,
        "sl_would_hit": bars_until_sl is not None,
    }


async def _fetch_candles(
    symbol: str, start_ts: int, end_ts: int, resolution: str = "5m"
) -> List[Dict[str, Any]]:
    try:
        from agent.data.delta_client import DeltaExchangeClient
    except ImportError:
        return []
    client = DeltaExchangeClient()
    try:
        resp = await client.get_candles(
            symbol=symbol,
            resolution=resolution,
            start=start_ts,
            end=end_ts,
        )
        result = resp.get("result") if isinstance(resp, dict) else None
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and isinstance(result.get("candles"), list):
            return result["candles"]
    except Exception as exc:
        print(f"Candle fetch failed for {symbol}: {exc}", file=sys.stderr)
    return []


async def replay_trades(
    trades: List[Dict[str, Any]], resolution: str, use_api: bool
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for t in trades:
        entry = float(t.get("entry_price") or 0)
        exit_p = float(t.get("exit_price") or 0)
        side = str(t.get("side") or "long")
        meta = t.get("metadata") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        sl, tp = _sl_tp_from_meta(meta)

        opened = t.get("opened_at") or t.get("closed_at")
        closed = t.get("closed_at")
        row: Dict[str, Any] = {
            "symbol": t.get("symbol"),
            "side": side,
            "entry_price": entry,
            "exit_price": exit_p,
            "pnl": float(t.get("pnl") or 0),
            "close_reason": t.get("close_reason"),
        }

        if not use_api or entry <= 0:
            is_long = side.lower() in ("long", "buy")
            mfe = max(0.0, (exit_p - entry) if is_long else (entry - exit_p))
            mae = max(0.0, (entry - exit_p) if is_long else (exit_p - entry))
            row["excursions"] = {
                "bars_held": None,
                "mfe_usd": round(mfe, 2),
                "mae_usd": round(mae, 2),
                "mode": "price_delta_only",
                "tp_would_hit": None,
                "sl_would_hit": None,
            }
            results.append(row)
            continue

        if opened is None or closed is None:
            results.append(row)
            continue
        if hasattr(opened, "timestamp"):
            start_ts = int(opened.timestamp())
        else:
            start_ts = int(datetime.fromisoformat(str(opened).replace("Z", "+00:00")).timestamp())
        if hasattr(closed, "timestamp"):
            end_ts = int(closed.timestamp()) + 300
        else:
            end_ts = int(datetime.fromisoformat(str(closed).replace("Z", "+00:00")).timestamp()) + 300

        candles = await _fetch_candles(str(t["symbol"]), start_ts, end_ts, resolution)
        if candles:
            row["excursions"] = _compute_excursions(
                side=side, entry_price=entry, candles=candles, sl=sl, tp=tp
            )
            row["excursions"]["mode"] = "candle_replay"
        else:
            row["excursions"] = {"mode": "no_candles", "bars_held": 0}
        results.append(row)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="MFE/MAE trade excursion replay")
    parser.add_argument("--start", default="2026-06-29")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--resolution", default="5m")
    parser.add_argument("--use-api", action="store_true", help="Fetch candles from Delta API")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    trades = _fetch_trades(args.start, args.end)
    if not trades:
        print("No trades or DATABASE_URL not set", file=sys.stderr)
        return 2

    results = asyncio.run(replay_trades(trades, args.resolution, args.use_api))

    mfe_vals = [
        r["excursions"]["mfe_usd"]
        for r in results
        if r.get("excursions") and r["excursions"].get("mfe_usd") is not None
    ]
    mae_vals = [
        r["excursions"]["mae_usd"]
        for r in results
        if r.get("excursions") and r["excursions"].get("mae_usd") is not None
    ]
    tp_hits = sum(
        1 for r in results if r.get("excursions", {}).get("tp_would_hit") is True
    )
    sl_hits = sum(
        1 for r in results if r.get("excursions", {}).get("sl_would_hit") is True
    )

    print(f"Trades replayed: {len(results)}")
    if mfe_vals:
        print(f"Avg MFE: ${sum(mfe_vals)/len(mfe_vals):.2f}  Avg MAE: ${sum(mae_vals)/len(mae_vals):.2f}")
    print(f"TP would have hit: {tp_hits}  SL would have hit: {sl_hits}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
