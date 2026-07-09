#!/usr/bin/env python3
"""Economic replay for rejected entries: SL/TP, fees, and slippage."""

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


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _entry_context(obj: Dict[str, Any]) -> Dict[str, Any]:
    mc = obj.get("market_context") if isinstance(obj.get("market_context"), dict) else {}
    features = mc.get("features") if isinstance(mc.get("features"), dict) else {}
    price = None
    for source in (mc.get("current_price"), features.get("close"), features.get("price")):
        if source is None:
            continue
        try:
            px = float(source)
            if px > 0:
                price = px
                break
        except (TypeError, ValueError):
            continue
    atr = features.get("atr_14")
    try:
        atr_f = float(atr) if atr is not None else None
    except (TypeError, ValueError):
        atr_f = None
    return {"entry_price": price, "atr_14": atr_f, "features": features}


def _sl_tp_prices(
    *,
    side: str,
    entry_price: float,
    atr_14: Optional[float],
    sl_mult: float,
    tp_mult: float,
    stop_pct: float,
    take_pct: float,
    use_atr: bool,
) -> tuple[float, float]:
    is_long = side.lower() in ("long", "buy")
    if use_atr and atr_14 is not None and atr_14 > 0:
        sl_dist = max(entry_price * stop_pct, atr_14 * sl_mult)
        tp_dist = max(entry_price * take_pct, atr_14 * tp_mult)
    else:
        sl_dist = entry_price * stop_pct
        tp_dist = entry_price * take_pct
    if is_long:
        return entry_price - sl_dist, entry_price + tp_dist
    return entry_price + sl_dist, entry_price - tp_dist


def _net_pnl_pct(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    taker_fee_rate: float,
    slippage_bps: float,
) -> float:
    slip = slippage_bps / 10000.0
    fee_rt = taker_fee_rate * 2.0
    is_long = side.lower() in ("long", "buy")
    if is_long:
        eff_entry = entry_price * (1.0 + slip)
        eff_exit = exit_price * (1.0 - slip)
        gross = (eff_exit - eff_entry) / eff_entry
    else:
        eff_entry = entry_price * (1.0 - slip)
        eff_exit = exit_price * (1.0 + slip)
        gross = (eff_entry - eff_exit) / eff_entry
    return (gross - fee_rt) * 100.0


async def _replay_one(
    obj: Dict[str, Any],
    *,
    horizon_bars: int,
    bar_minutes: int,
    sl_mult: float,
    tp_mult: float,
    stop_pct: float,
    take_pct: float,
    use_atr: bool,
    taker_fee_rate: float,
    slippage_bps: float,
) -> Optional[Dict[str, Any]]:
    from agent.persistence.trade_excursions import compute_excursions

    signal = str(obj.get("signal") or "").upper()
    if signal not in ("LONG", "SHORT"):
        return None
    ts = _parse_ts(obj.get("timestamp"))
    ctx = _entry_context(obj)
    entry_price = ctx.get("entry_price")
    if ts is None or entry_price is None:
        return None

    side = "buy" if signal == "LONG" else "sell"
    sl, tp = _sl_tp_prices(
        side=signal,
        entry_price=float(entry_price),
        atr_14=ctx.get("atr_14"),
        sl_mult=sl_mult,
        tp_mult=tp_mult,
        stop_pct=stop_pct,
        take_pct=take_pct,
        use_atr=use_atr,
    )
    symbol = str(obj.get("symbol") or "BTCUSD")
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
            "reject_reason": obj.get("reason"),
            "error": str(exc),
        }

    if not candles:
        return None

    exc = compute_excursions(
        side=side, entry_price=float(entry_price), candles=candles, sl=sl, tp=tp
    )
    exit_price = float(candles[-1].get("close") or entry_price)
    if exc.get("sl_would_hit"):
        exit_price = sl
        outcome = "sl_hit"
    elif exc.get("tp_would_hit"):
        exit_price = tp
        outcome = "tp_hit"
    else:
        outcome = "time_exit"

    net_pct = _net_pnl_pct(
        side=signal,
        entry_price=float(entry_price),
        exit_price=exit_price,
        taker_fee_rate=taker_fee_rate,
        slippage_bps=slippage_bps,
    )
    gross_pct = (
        (exit_price - float(entry_price)) / float(entry_price) * 100.0
        if signal == "LONG"
        else (float(entry_price) - exit_price) / float(entry_price) * 100.0
    )
    return {
        "event_id": obj.get("event_id"),
        "timestamp": obj.get("timestamp"),
        "symbol": symbol,
        "signal": signal,
        "reject_reason": obj.get("reason"),
        "entry_price": float(entry_price),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "outcome": outcome,
        "gross_return_pct": round(gross_pct, 4),
        "net_return_pct": round(net_pct, 4),
        "would_have_won_gross": gross_pct > 0,
        "would_have_won_net": net_pct > 0,
        "forward_mfe_pct": exc.get("mfe_pct"),
        "forward_mae_pct": exc.get("mae_pct"),
        "adx_14": ctx["features"].get("adx_14"),
    }


async def run_economic_replay(
    log_path: Path,
    *,
    horizon_bars: int,
    reject_filter: Optional[str] = None,
) -> Dict[str, Any]:
    from agent.core.config import settings

    text = log_path.read_text(encoding="utf-8", errors="replace")
    rows: List[Dict[str, Any]] = []
    for obj in _iter_json_objects(text):
        if obj.get("event") != "trading_entry_rejected":
            continue
        reason = str(obj.get("reason") or "")
        if reason == "hold_at_synthesis":
            continue
        if reject_filter and reason != reject_filter:
            continue
        replay = await _replay_one(
            obj,
            horizon_bars=horizon_bars,
            bar_minutes=5,
            sl_mult=float(getattr(settings, "atr_sl_distance_mult", 1.0) or 1.0),
            tp_mult=float(getattr(settings, "atr_tp_distance_mult", 1.5) or 1.5),
            stop_pct=float(getattr(settings, "stop_loss_percentage", 0.01) or 0.01),
            take_pct=float(getattr(settings, "take_profit_percentage", 0.015) or 0.015),
            use_atr=bool(getattr(settings, "use_atr_scaled_sl_tp", False)),
            taker_fee_rate=float(getattr(settings, "taker_fee_rate", 0.0005) or 0.0005),
            slippage_bps=float(getattr(settings, "slippage_bps", 5.0) or 5.0),
        )
        if replay:
            rows.append(replay)

    by_reason: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_reason[str(row.get("reject_reason") or "unknown")].append(row)

    summary = []
    for reason, group in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        net_rets = [
            float(g["net_return_pct"])
            for g in group
            if g.get("net_return_pct") is not None
        ]
        gross_rets = [
            float(g["gross_return_pct"])
            for g in group
            if g.get("gross_return_pct") is not None
        ]
        net_wins = sum(1 for g in group if g.get("would_have_won_net"))
        summary.append(
            {
                "reject_reason": reason,
                "n": len(group),
                "pct_would_win_net": round(net_wins / len(group) * 100.0, 2) if group else 0.0,
                "avg_net_return_pct": round(sum(net_rets) / len(net_rets), 4) if net_rets else None,
                "avg_gross_return_pct": (
                    round(sum(gross_rets) / len(gross_rets), 4) if gross_rets else None
                ),
                "net_expectancy_positive": (sum(net_rets) / len(net_rets) > 0) if net_rets else False,
            }
        )

    adx_rows = [r for r in rows if str(r.get("reject_reason")) == "v15_adx_trending_filter"]
    adx_net = [float(r["net_return_pct"]) for r in adx_rows if r.get("net_return_pct") is not None]
    promotion_gate = {
        "adx_cohort_n": len(adx_rows),
        "adx_min_sample": 30,
        "adx_net_expectancy_positive": (sum(adx_net) / len(adx_net) > 0) if adx_net else False,
        "adx_avg_net_return_pct": round(sum(adx_net) / len(adx_net), 4) if adx_net else None,
        "promotion_blocked": len(adx_rows) < 30
        or not ((sum(adx_net) / len(adx_net) > 0) if adx_net else False),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_bars": horizon_bars,
        "replayed_count": len(rows),
        "summary_by_reject_reason": summary,
        "promotion_gate_3b": promotion_gate,
        "rows": rows,
        "assumptions": {
            "taker_fee_rate_per_side": float(getattr(settings, "taker_fee_rate", 0.0005)),
            "slippage_bps": float(getattr(settings, "slippage_bps", 5.0)),
            "use_atr_scaled_sl_tp": bool(getattr(settings, "use_atr_scaled_sl_tp", False)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_file", type=Path)
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--reject-reason", type=str, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "investigation" / "economic_replay_2026-07-09.json",
    )
    args = parser.parse_args()
    result = asyncio.run(
        run_economic_replay(
            args.log_file,
            horizon_bars=args.horizon_bars,
            reject_filter=args.reject_reason,
        )
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result["summary_by_reject_reason"], indent=2))
    print(json.dumps(result["promotion_gate_3b"], indent=2))
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
