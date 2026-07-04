"""MFE/MAE and TP/SL excursion computation for closed trades."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def sl_tp_from_metadata(meta: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Extract stop-loss and take-profit from close metadata."""
    summary = (
        meta.get("entry_state_summary")
        if isinstance(meta.get("entry_state_summary"), dict)
        else {}
    )
    sl = summary.get("stop_loss_at_entry")
    tp = summary.get("take_profit_at_entry")
    if sl is None or tp is None:
        dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
        sl = sl or dc.get("stop_loss_at_entry")
        tp = tp or dc.get("take_profit_at_entry")
    try:
        return (
            float(sl) if sl is not None else None,
            float(tp) if tp is not None else None,
        )
    except (TypeError, ValueError):
        return None, None


def compute_excursions(
    *,
    side: str,
    entry_price: float,
    candles: List[Dict[str, Any]],
    sl: Optional[float],
    tp: Optional[float],
) -> Dict[str, Any]:
    """Compute MFE/MAE and TP/SL hit timing from OHLC candles."""
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
        "mode": "candle_replay",
    }


def price_delta_excursions(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
) -> Dict[str, Any]:
    """Fallback excursions from entry/exit only."""
    is_long = str(side).lower() in ("long", "buy")
    mfe = max(0.0, (exit_price - entry_price) if is_long else (entry_price - exit_price))
    mae = max(0.0, (entry_price - exit_price) if is_long else (exit_price - entry_price))
    return {
        "bars_held": None,
        "mfe_usd": round(mfe, 2),
        "mae_usd": round(mae, 2),
        "mfe_pct": round(mfe / entry_price * 100, 4) if entry_price else 0,
        "mae_pct": round(mae / entry_price * 100, 4) if entry_price else 0,
        "mode": "price_delta_only",
        "tp_would_hit": None,
        "sl_would_hit": None,
    }


async def compute_excursions_for_close(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    opened_at: Any,
    closed_at: Any,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Fetch candles when possible; fallback to price-delta excursions."""
    sl, tp = sl_tp_from_metadata(metadata)
    if entry_price <= 0:
        return price_delta_excursions(
            side=side, entry_price=entry_price or exit_price, exit_price=exit_price
        )
    try:
        from agent.data.delta_client import DeltaExchangeClient

        client = DeltaExchangeClient()
        start_ts = int(
            opened_at.timestamp()
            if hasattr(opened_at, "timestamp")
            else __import__("time").time() - 3600
        )
        end_ts = int(
            closed_at.timestamp()
            if hasattr(closed_at, "timestamp")
            else __import__("time").time()
        )
        resp = await client.get_candles(
            symbol=symbol,
            resolution="5m",
            start=start_ts,
            end=end_ts,
        )
        result = resp.get("result") if isinstance(resp, dict) else None
        candles: List[Dict[str, Any]] = []
        if isinstance(result, list):
            candles = result
        elif isinstance(result, dict) and isinstance(result.get("candles"), list):
            candles = result["candles"]
        if candles:
            return compute_excursions(
                side=side,
                entry_price=entry_price,
                candles=candles,
                sl=sl,
                tp=tp,
            )
    except Exception:
        pass
    return price_delta_excursions(
        side=side, entry_price=entry_price, exit_price=exit_price
    )
