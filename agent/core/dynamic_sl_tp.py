"""
Dynamic SL/TP levels and Delta position-bracket payload helpers.

Computes ATR/regime-aware stop and target prices, throttles exchange PUT updates,
and builds nested ``stop_loss_order`` / ``take_profit_order`` bodies for
``POST/PUT /v2/orders/bracket``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from agent.core.sl_tp import compute_stop_take_prices


@dataclass
class SlTpLevels:
    stop_loss: Optional[float]
    take_profit: Optional[float]
    trail_amount: Optional[float] = None


def compute_sl_tp_levels(
    entry: float,
    side: str,
    atr_14: Optional[float],
    regime: Optional[str],
    settings: Any,
    *,
    tick_size: Optional[float] = None,
) -> SlTpLevels:
    """Compute absolute SL/TP (and optional trail) from execution-time market state."""
    if entry <= 0:
        return SlTpLevels(None, None, None)

    side_u = str(side or "BUY").strip().upper()
    if side_u in ("LONG",):
        side_u = "BUY"
    if side_u in ("SHORT",):
        side_u = "SELL"

    use_atr = bool(getattr(settings, "use_atr_scaled_sl_tp", False)) and atr_14 is not None
    sl_pct = float(getattr(settings, "stop_loss_percentage", 0.01) or 0.01)
    tp_pct = float(getattr(settings, "take_profit_percentage", 0.02) or 0.02)

    regime_sl_tp_multipliers = {
        "crisis": (
            float(getattr(settings, "crisis_sl_multiplier", 1.2) or 1.2),
            1.2,
        ),
        "trending": (0.9, 1.3),
        "ranging": (
            float(getattr(settings, "ranging_sl_multiplier", 0.75) or 0.75),
            0.85,
        ),
        "neutral": (1.0, 1.0),
    }
    sl_mult, tp_mult = regime_sl_tp_multipliers.get(
        str(regime or "neutral").lower(), (1.0, 1.0)
    )
    sl_pct = sl_pct * sl_mult
    tp_pct = tp_pct * tp_mult

    stop_loss, take_profit = compute_stop_take_prices(
        entry,
        side_u,
        sl_pct,
        tp_pct,
        use_atr_scaled=use_atr,
        atr_14=atr_14,
        atr_sl_mult=float(getattr(settings, "atr_sl_distance_mult", 1.0) or 1.0),
        atr_tp_mult=float(getattr(settings, "atr_tp_distance_mult", 1.5) or 1.5),
        tick_size=tick_size,
    )

    trail_amount: Optional[float] = None
    if bool(getattr(settings, "use_atr_trailing_stop", False)) and atr_14 is not None:
        try:
            atr_f = float(atr_14)
            if atr_f > 0:
                trail_amount = atr_f * float(getattr(settings, "atr_trailing_mult", 1.0) or 1.0)
        except (TypeError, ValueError):
            trail_amount = None

    if str(regime or "").lower() == "trending" and atr_14 is not None and entry > 0:
        try:
            atr_f = float(atr_14)
            atr_tp_mult = float(getattr(settings, "atr_tp_distance_mult", 1.5) or 1.5)
            side_u = str(side or "BUY").strip().upper()
            if side_u in ("LONG",):
                side_u = "BUY"
            if side_u in ("SHORT",):
                side_u = "SELL"
            extended_tp = (
                entry + (atr_f * atr_tp_mult * 2.0)
                if side_u == "BUY"
                else entry - (atr_f * atr_tp_mult * 2.0)
            )
            if take_profit is not None:
                if side_u == "BUY" and extended_tp > take_profit:
                    take_profit = extended_tp
                elif side_u == "SELL" and extended_tp < take_profit:
                    take_profit = extended_tp
        except (TypeError, ValueError):
            pass

    return SlTpLevels(stop_loss, take_profit, trail_amount)


def _pct_change(old: Optional[float], new: Optional[float]) -> float:
    if old is None or new is None or old <= 0:
        return 1.0
    return abs(new - old) / old


def should_update_bracket(
    position: Dict[str, Any],
    new_levels: SlTpLevels,
    settings: Any,
) -> bool:
    """True when interval elapsed and SL/TP moved beyond minimum price change %."""
    min_interval = int(
        getattr(settings, "dynamic_sl_tp_min_adjust_interval_seconds", 60) or 60
    )
    min_chg = float(getattr(settings, "dynamic_sl_tp_min_price_change_pct", 0.002) or 0.002)

    last_raw = position.get("bracket_sl_tp_updated_at")
    if last_raw:
        try:
            if isinstance(last_raw, str):
                last_ts = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
            elif isinstance(last_raw, datetime):
                last_ts = last_raw
            else:
                last_ts = None
            if last_ts is not None:
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last_ts).total_seconds()
                if age < min_interval:
                    return False
        except (TypeError, ValueError):
            pass

    old_sl = position.get("stop_loss")
    old_tp = position.get("take_profit")
    try:
        old_sl_f = float(old_sl) if old_sl is not None else None
    except (TypeError, ValueError):
        old_sl_f = None
    try:
        old_tp_f = float(old_tp) if old_tp is not None else None
    except (TypeError, ValueError):
        old_tp_f = None

    sl_moved = _pct_change(old_sl_f, new_levels.stop_loss) >= min_chg
    tp_moved = _pct_change(old_tp_f, new_levels.take_profit) >= min_chg
    return sl_moved or tp_moved


def to_delta_bracket_payload(
    levels: SlTpLevels,
    *,
    trigger_method: str = "mark_price",
    use_trailing: bool = False,
) -> Dict[str, Any]:
    """Build CreateBracketOrderRequest body (position bracket — no size)."""
    payload: Dict[str, Any] = {
        "bracket_stop_trigger_method": trigger_method or "mark_price",
    }
    if levels.stop_loss is not None:
        sl_body: Dict[str, str] = {"order_type": "market_order"}
        if use_trailing and levels.trail_amount is not None and levels.trail_amount > 0:
            sl_body["trail_amount"] = str(levels.trail_amount)
        else:
            sl_body["stop_price"] = str(levels.stop_loss)
        payload["stop_loss_order"] = sl_body
    if levels.take_profit is not None:
        payload["take_profit_order"] = {
            "order_type": "market_order",
            "stop_price": str(levels.take_profit),
        }
    return payload


def levels_to_put_bracket_fields(levels: SlTpLevels) -> Dict[str, str]:
    """Flat bracket_* fields for PUT /v2/orders/bracket."""
    out: Dict[str, str] = {}
    if levels.stop_loss is not None:
        sl = str(levels.stop_loss)
        out["bracket_stop_loss_price"] = sl
        out["bracket_stop_loss_limit_price"] = sl
    if levels.take_profit is not None:
        tp = str(levels.take_profit)
        out["bracket_take_profit_price"] = tp
        out["bracket_take_profit_limit_price"] = tp
    if levels.trail_amount is not None and levels.trail_amount > 0:
        out["bracket_trail_amount"] = str(levels.trail_amount)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Flip-aware bracket update (bypasses throttle when flip risk is high)
# ─────────────────────────────────────────────────────────────────────────────


def compute_flip_adjusted_levels(
    position: Dict[str, Any],
    cached_features: Dict[str, Any],
    settings: Any,
    *,
    tick_size: Optional[float] = None,
) -> Tuple[Optional["SlTpLevels"], bool]:
    """
    Check for market flip risk and, if high, compute tightened SL/TP levels.

    This is called from _maybe_update_dynamic_bracket() BEFORE the normal
    throttle check — when flip risk is high, we bypass the interval throttle
    and update immediately.

    Returns:
        (levels, is_flip_triggered) — levels is None if no update needed.
        is_flip_triggered is True when a flip-risk tightening was applied,
        which tells the caller to skip the normal should_update_bracket() check.
    """
    from agent.core.market_flip_detector import (
        detect_market_flip_risk,
        compute_flip_tightened_levels,
    )

    flip_enabled = bool(getattr(settings, "flip_detection_enabled", True))
    if not flip_enabled:
        return None, False

    score_threshold = float(
        getattr(settings, "flip_score_threshold_low", 0.55) or 0.55
    )

    side_raw = position.get("side", "long")
    position_side = "long" if str(side_raw).lower() in ("long", "buy") else "short"
    symbol = str(position.get("symbol") or "UNKNOWN")

    snapshot = detect_market_flip_risk(
        cached_features,
        position_side,
        symbol,
        settings=settings,
    )

    if snapshot.score < score_threshold:
        return None, False

    current_price = float(position.get("current_price") or position.get("entry_price") or 0)
    entry = float(position.get("entry_price") or 0)
    current_sl = position.get("stop_loss")
    current_tp = position.get("take_profit")
    try:
        current_sl = float(current_sl) if current_sl is not None else None
    except (TypeError, ValueError):
        current_sl = None
    try:
        current_tp = float(current_tp) if current_tp is not None else None
    except (TypeError, ValueError):
        current_tp = None

    new_sl, new_tp = compute_flip_tightened_levels(
        entry,
        current_price,
        current_sl,
        current_tp,
        position_side,
        snapshot.score,
        settings=settings,
    )

    if tick_size is not None and tick_size > 0:
        from agent.core.futures_utils import round_to_tick
        if new_sl is not None:
            new_sl = round_to_tick(new_sl, tick_size)
        if new_tp is not None:
            new_tp = round_to_tick(new_tp, tick_size)

    sl_changed = new_sl is not None and new_sl != current_sl
    tp_changed = new_tp is not None and new_tp != current_tp
    if not sl_changed and not tp_changed:
        return None, False

    levels = SlTpLevels(
        stop_loss=new_sl,
        take_profit=new_tp,
        trail_amount=position.get("bracket_trail_amount"),
    )
    return levels, True
