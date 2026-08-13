"""Path-prediction execution helpers: SL/TP, soft R:R, edge×confidence sizing."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from feature_store.transformer_btcusd.contract import path_favorable_adverse


def resolve_favorable_adverse(
    mfe: float,
    mae: float,
    *,
    signal: str,
) -> Tuple[float, float]:
    """Direction-aware (favorable_pct, adverse_pct) from long-centric labels."""
    side = "SELL" if str(signal).upper() in ("SELL", "STRONG_SELL", "SHORT") else "BUY"
    return path_favorable_adverse(mfe, mae, side=side)


def compute_path_stop_take_pcts(
    *,
    mfe: float,
    mae: float,
    signal: str,
    sl_adverse_mult: float = 1.0,
    tp_favorable_mult: float = 1.0,
) -> Tuple[float, float, float, float]:
    """Return (stop_loss_pct, take_profit_pct, favorable_pct, adverse_pct)."""
    favorable, adverse = resolve_favorable_adverse(mfe, mae, signal=signal)
    sl_pct = max(0.0, float(sl_adverse_mult) * float(adverse))
    tp_pct = max(0.0, float(tp_favorable_mult) * float(favorable))
    return sl_pct, tp_pct, float(favorable), float(adverse)


def compute_path_stop_take_prices(
    entry_price: float,
    *,
    signal: str,
    mfe: float,
    mae: float,
    sl_adverse_mult: float = 1.0,
    tp_favorable_mult: float = 1.0,
    tick_size: Optional[float] = None,
    spread_estimate: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float], float, float]:
    """Absolute SL/TP from path heads. Returns (sl, tp, favorable_pct, adverse_pct)."""
    from agent.core.sl_tp import _enforce_min_sl_distance, compute_stop_take_prices

    if entry_price <= 0:
        return None, None, 0.0, 0.0
    sl_pct, tp_pct, favorable, adverse = compute_path_stop_take_pcts(
        mfe=mfe,
        mae=mae,
        signal=signal,
        sl_adverse_mult=sl_adverse_mult,
        tp_favorable_mult=tp_favorable_mult,
    )
    if sl_pct <= 0 and tp_pct <= 0:
        return None, None, favorable, adverse
    side = "SELL" if str(signal).upper() in ("SELL", "STRONG_SELL", "SHORT") else "BUY"
    sl, tp = compute_stop_take_prices(
        entry_price,
        side,
        sl_pct,
        tp_pct,
        use_atr_scaled=False,
        tick_size=tick_size,
        spread_estimate=spread_estimate,
    )
    sl = _enforce_min_sl_distance(
        entry_price,
        sl,
        tick_size=tick_size,
        spread_estimate=spread_estimate,
    )
    return sl, tp, favorable, adverse


def apply_soft_rr(
    *,
    signal: str,
    size_scale: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    min_risk_reward_ratio: float = 1.2,
    rr_size_factor: float = 0.7,
) -> Tuple[str, float, str, list[str]]:
    """Soft R:R: never HOLD; may strip STRONG and reduce size.

    Returns:
        (signal, size_scale, rr_soft_action, reason_codes)
    """
    codes: list[str] = []
    sig = str(signal or "HOLD").upper()
    scale = float(size_scale)
    action = "none"
    sl = max(float(stop_loss_pct), 1e-12)
    tp = max(float(take_profit_pct), 0.0)
    ratio = tp / sl if sl > 0 else 0.0
    min_rr = float(min_risk_reward_ratio)
    if sig in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL") and ratio < min_rr:
        if sig == "STRONG_BUY":
            sig = "BUY"
            action = "strip_strong"
            codes.append("path_rr_strip_strong")
        elif sig == "STRONG_SELL":
            sig = "SELL"
            action = "strip_strong"
            codes.append("path_rr_strip_strong")
        scale = max(0.0, scale * float(rr_size_factor))
        if action == "none":
            action = "reduce_size"
        else:
            action = "strip_strong"
        codes.append("path_rr_reduce_size")
    return sig, scale, action, codes


def compute_edge_confidence_size_scale(
    *,
    size_scale: float,
    winning_edge: float,
    threshold: float,
    size_floor: float = 0.35,
    edge_weight: float = 1.0,
) -> float:
    """Combine confidence size_scale with edge_ratio clip."""
    thr = max(float(threshold), 1e-6)
    edge_ratio = min(1.0, max(0.0, abs(float(winning_edge)) / thr))
    weighted = float(edge_weight) * edge_ratio
    if edge_weight <= 0:
        weighted = 1.0
    combined = float(size_scale) * float(max(float(size_floor), min(1.0, weighted)))
    return float(max(float(size_floor), min(1.0, combined)))


def build_execution_plan(
    *,
    signal: str,
    confidence: float,
    size_scale: float,
    long_edge: float,
    short_edge: float,
    winning_edge: float,
    threshold: float,
    primary_tf: str,
    mfe: float,
    mae: float,
    future_volatility: float,
    vol_regime: str,
    reason_codes: list[str],
    entry_portfolio_margin_fraction: float,
    size_floor: float = 0.35,
    edge_weight: float = 1.0,
    sl_adverse_mult: float = 1.0,
    tp_favorable_mult: float = 1.0,
    min_risk_reward_ratio: float = 1.2,
    rr_size_factor: float = 0.7,
) -> Dict[str, Any]:
    """Assemble execution_plan dict for DecisionReady / trading handler."""
    sl_pct, tp_pct, favorable, adverse = compute_path_stop_take_pcts(
        mfe=mfe,
        mae=mae,
        signal=signal,
        sl_adverse_mult=sl_adverse_mult,
        tp_favorable_mult=tp_favorable_mult,
    )
    sig, scale, rr_action, rr_codes = apply_soft_rr(
        signal=signal,
        size_scale=size_scale,
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
        min_risk_reward_ratio=min_risk_reward_ratio,
        rr_size_factor=rr_size_factor,
    )
    # Recompute brackets if signal stripped (same side family — pcts unchanged)
    final_scale = compute_edge_confidence_size_scale(
        size_scale=scale,
        winning_edge=winning_edge,
        threshold=threshold,
        size_floor=size_floor,
        edge_weight=edge_weight,
    )
    size_fraction = float(entry_portfolio_margin_fraction) * final_scale
    codes = list(reason_codes) + list(rr_codes)
    return {
        "signal": sig,
        "confidence": float(confidence),
        "size_scale": final_scale,
        "long_edge": float(long_edge),
        "short_edge": float(short_edge),
        "winning_edge": float(winning_edge),
        "primary_tf": str(primary_tf or ""),
        "mfe": float(mfe),
        "mae": float(mae),
        "favorable_pct": float(favorable),
        "adverse_pct": float(adverse),
        "future_volatility": float(future_volatility),
        "vol_regime": str(vol_regime),
        "stop_loss_pct": float(sl_pct),
        "take_profit_pct": float(tp_pct),
        "size_fraction": float(size_fraction),
        "reason_codes": codes,
        "rr_soft_action": rr_action,
        "threshold": float(threshold),
    }


def extract_execution_plan(market_context: Mapping[str, Any]) -> Dict[str, Any]:
    """Read execution_plan from market_context if present."""
    plan = market_context.get("execution_plan") if isinstance(market_context, Mapping) else None
    return dict(plan) if isinstance(plan, dict) else {}
