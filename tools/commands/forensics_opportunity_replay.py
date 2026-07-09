#!/usr/bin/env python3
"""Replay forward outcomes for non-HOLD trading_entry_rejected events from agent logs."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _iter_json_objects(text: str) -> Iterator[Dict[str, Any]]:
    dec = json.JSONDecoder()
    flat = re.sub(r"\s+", "", text)
    pos = 0
    while pos < len(flat):
        if flat[pos] != "{":
            pos += 1
            continue
        try:
            obj, end = dec.raw_decode(flat, pos)
            if isinstance(obj, dict):
                yield obj
            pos = end
        except json.JSONDecodeError:
            pos += 1


def _entry_price(obj: Dict[str, Any]) -> Optional[float]:
    mc = obj.get("market_context") if isinstance(obj.get("market_context"), dict) else {}
    for key in ("current_price", "close"):
        val = mc.get(key)
        if val is not None:
            try:
                px = float(val)
                if px > 0:
                    return px
            except (TypeError, ValueError):
                pass
    feats = mc.get("features") if isinstance(mc.get("features"), dict) else {}
    for key in ("close", "price"):
        val = feats.get(key)
        if val is not None:
            try:
                px = float(val)
                if px > 0:
                    return px
            except (TypeError, ValueError):
                pass
    return None


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _replay_one(
    obj: Dict[str, Any],
    *,
    horizon_bars: int,
    bar_minutes: int,
) -> Optional[Dict[str, Any]]:
    from agent.persistence.trade_excursions import compute_excursions

    signal = str(obj.get("signal") or "").upper()
    if signal not in ("LONG", "SHORT"):
        return None
    ts = _parse_ts(obj.get("timestamp"))
    entry_price = _entry_price(obj)
    if ts is None or entry_price is None:
        return None
    symbol = str(obj.get("symbol") or "BTCUSD")
    side = "buy" if signal == "LONG" else "sell"
    start_ts = int(ts.timestamp())
    end_ts = int((ts + timedelta(minutes=horizon_bars * bar_minutes)).timestamp())

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
    except Exception as exc:
        return {
            "event_id": obj.get("event_id"),
            "timestamp": obj.get("timestamp"),
            "symbol": symbol,
            "signal": signal,
            "reject_reason": obj.get("reason"),
            "entry_price": entry_price,
            "error": str(exc),
        }

    if not candles:
        return None

    last_close = float(candles[-1].get("close") or entry_price)
    exc = compute_excursions(side=side, entry_price=entry_price, candles=candles, sl=None, tp=None)
    is_long = signal == "LONG"
    forward_return_pct = (
        (last_close - entry_price) / entry_price * 100.0
        if is_long
        else (entry_price - last_close) / entry_price * 100.0
    )
    return {
        "event_id": obj.get("event_id"),
        "timestamp": obj.get("timestamp"),
        "symbol": symbol,
        "signal": signal,
        "reject_reason": obj.get("reason"),
        "entry_price": entry_price,
        "forward_return_pct": round(forward_return_pct, 4),
        "forward_mfe_pct": exc.get("mfe_pct"),
        "forward_mae_pct": exc.get("mae_pct"),
        "would_have_won": forward_return_pct > 0,
        "adx_14": (obj.get("market_context") or {}).get("features", {}).get("adx_14")
        if isinstance(obj.get("market_context"), dict)
        else obj.get("adx"),
    }


async def run_replay(log_path: Path, *, horizon_bars: int) -> Dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    rows: List[Dict[str, Any]] = []
    for obj in _iter_json_objects(text):
        if obj.get("event") != "trading_entry_rejected":
            continue
        if str(obj.get("reason")) == "hold_at_synthesis":
            continue
        replay = await _replay_one(obj, horizon_bars=horizon_bars, bar_minutes=5)
        if replay:
            rows.append(replay)

    by_reason: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_reason[str(row.get("reject_reason") or "unknown")].append(row)

    summary = []
    for reason, group in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        wins = sum(1 for g in group if g.get("would_have_won"))
        rets = [float(g["forward_return_pct"]) for g in group if g.get("forward_return_pct") is not None]
        summary.append(
            {
                "reject_reason": reason,
                "n": len(group),
                "pct_would_win": round(wins / len(group) * 100.0, 2) if group else 0.0,
                "avg_forward_return_pct": round(sum(rets) / len(rets), 4) if rets else None,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_bars": horizon_bars,
        "replayed_count": len(rows),
        "summary_by_reject_reason": summary,
        "rows": rows,
        "label_entry_decisions_note": (
            "entry_decisions metadata lacks decision_context.features.close; "
            "replay sourced from agent log trading_entry_rejected payloads."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_file", type=Path)
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "investigation" / "opportunity_replay_2026-07-09.json",
    )
    args = parser.parse_args()
    result = asyncio.run(run_replay(args.log_file, horizon_bars=args.horizon_bars))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result["summary_by_reject_reason"], indent=2))
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
