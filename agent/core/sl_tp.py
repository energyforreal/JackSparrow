"""
Shared stop-loss / take-profit price computation.

Single source of truth for ATR-scaled and fixed-percentage SL/TP, plus tick rounding
for exchange-valid prices. Used by TradingEventHandler and ExecutionEngine.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from agent.core.futures_utils import round_to_tick


def parse_risk_approved_side(side_raw: Any) -> Optional[str]:
    """Normalize payload side to ``BUY`` or ``SELL``. Returns None if unusable."""
    if side_raw is None:
        s = "BUY"
    else:
        s = str(side_raw).strip().upper()
    if s in ("BUY", "LONG"):
        return "BUY"
    if s in ("SELL", "SHORT"):
        return "SELL"
    return None


def compute_stop_take_prices(
    entry_price: float,
    side: str,
    stop_loss_pct: float,
    take_profit_pct: float,
    *,
    use_atr_scaled: bool = False,
    atr_14: Optional[float] = None,
    atr_sl_mult: float = 1.0,
    atr_tp_mult: float = 1.5,
    tick_size: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Compute absolute stop-loss and take-profit prices.

    When ``use_atr_scaled`` is True and ``atr_14`` is a positive float, uses
    ``distance = max(entry * pct, atr * mult)`` for SL and TP legs (same as legacy handler).

    Otherwise uses fixed fractions of entry (only sets a level if the corresponding pct is truthy).

    Args:
        entry_price: Reference entry (quote currency).
        side: ``BUY`` or ``SELL`` (case-insensitive).
        stop_loss_pct: Fraction of price (e.g. 0.01 = 1%).
        take_profit_pct: Fraction of price.
        use_atr_scaled: Whether to try ATR scaling.
        atr_14: ATR(14) in price units when available.
        atr_sl_mult: ATR multiplier for stop distance.
        atr_tp_mult: ATR multiplier for take-profit distance.
        tick_size: If set, round outputs to this tick (Delta-style).

    Returns:
        (stop_loss, take_profit) — either may be None if pct is zero / invalid input.
    """
    if entry_price <= 0 or not (entry_price == entry_price):  # NaN
        return None, None

    s = str(side or "BUY").strip().upper()
    if s in ("LONG",):
        s = "BUY"
    if s in ("SHORT",):
        s = "SELL"
    if s not in ("BUY", "SELL"):
        return None, None

    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    atr_ok = False
    if use_atr_scaled and atr_14 is not None:
        try:
            atr_f = float(atr_14)
            if atr_f > 0:
                sl_dist = max(entry_price * float(stop_loss_pct), atr_f * float(atr_sl_mult))
                tp_dist = max(entry_price * float(take_profit_pct), atr_f * float(atr_tp_mult))
                if s == "BUY":
                    stop_loss = entry_price - sl_dist
                    take_profit = entry_price + tp_dist
                else:
                    stop_loss = entry_price + sl_dist
                    take_profit = entry_price - tp_dist
                atr_ok = True
        except (TypeError, ValueError):
            pass

    if not atr_ok:
        stop_loss = None
        take_profit = None
        if stop_loss_pct:
            if s == "BUY":
                stop_loss = entry_price * (1.0 - float(stop_loss_pct))
            else:
                stop_loss = entry_price * (1.0 + float(stop_loss_pct))
        if take_profit_pct:
            if s == "BUY":
                take_profit = entry_price * (1.0 + float(take_profit_pct))
            else:
                take_profit = entry_price * (1.0 - float(take_profit_pct))

    ts = float(tick_size) if tick_size is not None and float(tick_size) > 0 else None
    if ts is not None:
        if stop_loss is not None:
            stop_loss = round_to_tick(stop_loss, ts)
        if take_profit is not None:
            take_profit = round_to_tick(take_profit, ts)

    return stop_loss, take_profit


def rebase_sl_tp_to_fill(
    planned_entry: float,
    fill_price: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    tick_size: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Shift absolute SL/TP by ``fill_price - planned_entry`` so distances match the fill.

    Use in paper mode when the simulated fill differs from the approval reference price.
    """
    if stop_loss is None and take_profit is None:
        return None, None
    try:
        pe = float(planned_entry)
        fp = float(fill_price)
    except (TypeError, ValueError):
        return stop_loss, take_profit
    if pe <= 0 or not (pe == pe) or not (fp == fp):
        return stop_loss, take_profit
    adj = fp - pe
    new_sl = stop_loss + adj if stop_loss is not None else None
    new_tp = take_profit + adj if take_profit is not None else None
    ts = float(tick_size) if tick_size is not None and float(tick_size) > 0 else None
    if ts is not None:
        if new_sl is not None:
            new_sl = round_to_tick(new_sl, ts)
        if new_tp is not None:
            new_tp = round_to_tick(new_tp, ts)
    return new_sl, new_tp
