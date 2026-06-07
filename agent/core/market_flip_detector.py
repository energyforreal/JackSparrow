"""
Market Flip Detector — scores the probability of an imminent trend reversal.

Reads cached feature snapshots (RSI, MACD, EMA cross, momentum, regime) and
produces a FlipRiskSnapshot with a 0-1 score and per-signal breakdown.

The score is consumed by _maybe_update_dynamic_bracket() in execution.py to:
  - Bypass the normal throttle interval and immediately tighten SL/TP
  - Apply a tighter multiplier (flip_sl_tighten_mult) to reduce risk
  - Extend TP conservatively so profit is locked before the move

FLIP CONDITIONS SCORED (each 0 or 1):
  1. RSI overbought/oversold         → RSI > 72 (long) or RSI < 28 (short)
  2. MACD histogram cross            → hist sign flip in last 2 bars
  3. EMA fast/slow cross adverse     → ema_9 crosses below ema_21 for long, above for short
  4. Momentum exhaustion             → momentum_10 and momentum_20 diverge against position
  5. Regime flip                     → regime changed from trending → ranging/crisis
  6. ADX collapse                    → ADX was >22 now <18 (trend weakening)
  7. ATR spike                       → ATR % increase >30% in one bar (volatility shock)

Score = weighted average of triggered conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import time

import structlog

logger = structlog.get_logger()


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FlipSignal:
    name: str
    triggered: bool
    weight: float
    detail: str = ""


@dataclass
class FlipRiskSnapshot:
    """Output of detect_market_flip_risk()."""
    score: float
    triggered_signals: List[FlipSignal]
    all_signals: List[FlipSignal]
    position_side: str
    symbol: str
    computed_at: float = field(default_factory=time.time)

    @property
    def is_high_risk(self) -> bool:
        """True when score exceeds the default high-risk threshold (0.55)."""
        return self.score >= 0.55

    @property
    def signal_names(self) -> List[str]:
        return [s.name for s in self.triggered_signals]

    def __repr__(self) -> str:
        return (
            f"FlipRiskSnapshot(symbol={self.symbol}, side={self.position_side}, "
            f"score={self.score:.3f}, signals={self.signal_names})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Feature extraction helpers
# ─────────────────────────────────────────────────────────────────────────────


def _f(features: Dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = features.get(key)
    if raw is None:
        return default
    try:
        v = float(raw)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _prev_features(features: Dict[str, Any]) -> Dict[str, Any]:
    """Return previous-bar feature dict if the feature cache stores history."""
    prev = features.get("prev") or features.get("previous_bar") or {}
    return prev if isinstance(prev, dict) else {}


# ─────────────────────────────────────────────────────────────────────────────
# Individual signal detectors
# ─────────────────────────────────────────────────────────────────────────────


def _signal_rsi_extreme(
    features: Dict[str, Any],
    position_side: str,
    *,
    overbought: float = 72.0,
    oversold: float = 28.0,
) -> FlipSignal:
    """RSI overbought (for longs) or oversold (for shorts) = exhaustion warning."""
    rsi = _f(features, "rsi_14", 50.0)
    if rsi == 50.0:
        rsi = _f(features, "BTCUSD_rsi_14", _f(features, "rsi", 50.0))

    if position_side == "long":
        triggered = rsi >= overbought
        detail = f"rsi={rsi:.1f} >= overbought={overbought}"
    else:
        triggered = rsi <= oversold
        detail = f"rsi={rsi:.1f} <= oversold={oversold}"

    return FlipSignal("rsi_extreme", triggered, weight=0.20, detail=detail)


def _signal_macd_hist_cross(
    features: Dict[str, Any],
    position_side: str,
) -> FlipSignal:
    """MACD histogram sign flip against position = momentum shift."""
    curr_hist = _f(features, "macd_hist", _f(features, "macd_histogram", 0.0))
    prev = _prev_features(features)
    prev_hist = _f(prev, "macd_hist", _f(prev, "macd_histogram", curr_hist))

    if position_side == "long":
        triggered = prev_hist > 0 and curr_hist < 0
        detail = f"macd_hist prev={prev_hist:.4f} → curr={curr_hist:.4f}"
    else:
        triggered = prev_hist < 0 and curr_hist > 0
        detail = f"macd_hist prev={prev_hist:.4f} → curr={curr_hist:.4f}"

    return FlipSignal("macd_hist_cross", triggered, weight=0.20, detail=detail)


def _signal_ema_cross_adverse(
    features: Dict[str, Any],
    position_side: str,
) -> FlipSignal:
    """EMA9 crossing below EMA21 (for longs) or above (for shorts) = trend death cross."""
    ema9 = _f(features, "ema_9", 0.0)
    ema21 = _f(features, "ema_21", 0.0)
    prev = _prev_features(features)
    prev_ema9 = _f(prev, "ema_9", ema9)
    prev_ema21 = _f(prev, "ema_21", ema21)

    if ema9 == 0.0 or ema21 == 0.0:
        return FlipSignal("ema_cross_adverse", False, weight=0.15, detail="ema data unavailable")

    if position_side == "long":
        triggered = (prev_ema9 > prev_ema21) and (ema9 <= ema21)
        detail = f"ema9={ema9:.2f} crossed below ema21={ema21:.2f}"
    else:
        triggered = (prev_ema9 < prev_ema21) and (ema9 >= ema21)
        detail = f"ema9={ema9:.2f} crossed above ema21={ema21:.2f}"

    return FlipSignal("ema_cross_adverse", triggered, weight=0.15, detail=detail)


def _signal_momentum_exhaustion(
    features: Dict[str, Any],
    position_side: str,
) -> FlipSignal:
    """Momentum 10 and 20 both turning against position = broad momentum loss."""
    m10 = _f(features, "momentum_10", 0.0)
    m20 = _f(features, "momentum_20", 0.0)
    prev = _prev_features(features)
    pm10 = _f(prev, "momentum_10", m10)
    pm20 = _f(prev, "momentum_20", m20)

    if position_side == "long":
        m10_adverse = m10 < 0 and pm10 >= 0
        triggered = m10_adverse or (m10 < 0 and m20 < 0)
        detail = f"momentum_10={m10:.2f}, momentum_20={m20:.2f}"
    else:
        m10_adverse = m10 > 0 and pm10 <= 0
        triggered = m10_adverse or (m10 > 0 and m20 > 0)
        detail = f"momentum_10={m10:.2f}, momentum_20={m20:.2f}"

    return FlipSignal("momentum_exhaustion", triggered, weight=0.15, detail=detail)


def _signal_regime_deterioration(
    features: Dict[str, Any],
    position_side: str,
) -> FlipSignal:
    """Regime changed away from trending, or crisis regime detected."""
    regime = str(features.get("regime") or "neutral").lower()
    prev = _prev_features(features)
    prev_regime = str(prev.get("regime") or regime).lower()

    crisis = regime == "crisis"
    trend_died = prev_regime == "trending" and regime in ("ranging", "neutral", "unknown")

    triggered = crisis or trend_died
    detail = f"regime: {prev_regime} → {regime}"

    return FlipSignal("regime_deterioration", triggered, weight=0.15, detail=detail)


def _signal_adx_collapse(
    features: Dict[str, Any],
    *,
    adx_trend_min: float = 22.0,
    adx_collapse_max: float = 18.0,
) -> FlipSignal:
    """ADX was above trend threshold, now collapsed below collapse level = trend ending."""
    adx = _f(features, "adx_14", 25.0)
    prev = _prev_features(features)
    prev_adx = _f(prev, "adx_14", adx)

    triggered = (prev_adx >= adx_trend_min) and (adx < adx_collapse_max)
    detail = f"adx prev={prev_adx:.1f} → curr={adx:.1f} (collapse_max={adx_collapse_max})"

    return FlipSignal("adx_collapse", triggered, weight=0.10, detail=detail)


def _signal_atr_spike(
    features: Dict[str, Any],
    *,
    spike_pct_threshold: float = 0.30,
) -> FlipSignal:
    """ATR jumped >30% in one bar = volatility shock, potential reversal."""
    atr_pct = _f(features, "atr_pct", 0.0)
    prev = _prev_features(features)
    prev_atr_pct = _f(prev, "atr_pct", atr_pct)

    if prev_atr_pct <= 0:
        return FlipSignal("atr_spike", False, weight=0.05, detail="prev atr_pct unavailable")

    increase = (atr_pct - prev_atr_pct) / prev_atr_pct if prev_atr_pct > 0 else 0.0
    triggered = increase >= spike_pct_threshold
    detail = f"atr_pct prev={prev_atr_pct:.4f} → curr={atr_pct:.4f} (+{increase*100:.1f}%)"

    return FlipSignal("atr_spike", triggered, weight=0.05, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# Main detector
# ─────────────────────────────────────────────────────────────────────────────


def detect_market_flip_risk(
    features: Dict[str, Any],
    position_side: str,
    symbol: str,
    *,
    settings: Any = None,
) -> FlipRiskSnapshot:
    """
    Score the probability of an imminent trend reversal for an open position.

    Args:
        features:       Cached feature dict from MarketDataService (current bar).
                        If it contains a "prev" or "previous_bar" sub-dict, previous-bar
                        signals (MACD cross, EMA cross, ADX collapse) are computed.
        position_side:  "long" or "short"
        symbol:         Trading symbol (for logging)
        settings:       Agent settings object; optional — used for threshold overrides.

    Returns:
        FlipRiskSnapshot with 0-1 score and per-signal breakdown.
    """
    side = str(position_side or "long").lower()

    rsi_ob = float(getattr(settings, "flip_rsi_overbought", 72.0) or 72.0) if settings else 72.0
    rsi_os = float(getattr(settings, "flip_rsi_oversold", 28.0) or 28.0) if settings else 28.0
    adx_trend = float(getattr(settings, "flip_adx_trend_min", 22.0) or 22.0) if settings else 22.0
    adx_coll = float(getattr(settings, "flip_adx_collapse_max", 18.0) or 18.0) if settings else 18.0
    atr_spike = float(getattr(settings, "flip_atr_spike_pct", 0.30) or 0.30) if settings else 0.30

    signals = [
        _signal_rsi_extreme(features, side, overbought=rsi_ob, oversold=rsi_os),
        _signal_macd_hist_cross(features, side),
        _signal_ema_cross_adverse(features, side),
        _signal_momentum_exhaustion(features, side),
        _signal_regime_deterioration(features, side),
        _signal_adx_collapse(features, adx_trend_min=adx_trend, adx_collapse_max=adx_coll),
        _signal_atr_spike(features, spike_pct_threshold=atr_spike),
    ]

    total_weight = sum(s.weight for s in signals)
    triggered = [s for s in signals if s.triggered]
    triggered_weight = sum(s.weight for s in triggered)

    score = (triggered_weight / total_weight) if total_weight > 0 else 0.0

    if triggered:
        logger.info(
            "flip_risk_detected",
            symbol=symbol,
            side=side,
            score=round(score, 3),
            signals=[s.name for s in triggered],
        )

    return FlipRiskSnapshot(
        score=score,
        triggered_signals=triggered,
        all_signals=signals,
        position_side=side,
        symbol=symbol,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bracket adjustment helper
# ─────────────────────────────────────────────────────────────────────────────


def compute_flip_tightened_levels(
    entry: float,
    current_price: float,
    current_sl: Optional[float],
    current_tp: Optional[float],
    position_side: str,
    flip_score: float,
    *,
    settings: Any = None,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Given a flip risk score, tighten SL and pull TP closer to lock in profit.

    Tightening factors:
      - sl_tighten_mult: how much to pull SL toward current price
        e.g. 0.5 means SL distance from current_price = 0.5 × original_distance
      - tp_lock_mult: pull TP toward current price to lock in partial profit
        e.g. 0.7 means new_TP = current + 0.7 × (old_TP - current)
      - Both scale with flip_score: at score=0.55, gentle; at score=1.0, maximum tightening.

    Returns:
        (new_sl, new_tp) — None values mean "leave unchanged".
    """
    if entry <= 0 or current_price <= 0:
        return current_sl, current_tp

    side = str(position_side or "long").lower()

    sl_mult_min = float(getattr(settings, "flip_sl_tighten_mult_min", 0.5) or 0.5) if settings else 0.5
    sl_mult_max = float(getattr(settings, "flip_sl_tighten_mult_max", 0.85) or 0.85) if settings else 0.85
    tp_mult_min = float(getattr(settings, "flip_tp_lock_mult_min", 0.50) or 0.50) if settings else 0.50
    tp_mult_max = float(getattr(settings, "flip_tp_lock_mult_max", 0.80) or 0.80) if settings else 0.80
    score_low = float(getattr(settings, "flip_score_threshold_low", 0.55) or 0.55) if settings else 0.55

    if flip_score <= score_low:
        t = 0.0
    else:
        t = min(1.0, (flip_score - score_low) / (1.0 - score_low))

    sl_mult = sl_mult_max - t * (sl_mult_max - sl_mult_min)
    tp_mult = tp_mult_max - t * (tp_mult_max - tp_mult_min)

    new_sl = current_sl
    new_tp = current_tp

    if side == "long":
        if current_sl is not None and current_sl < current_price:
            sl_dist = current_price - current_sl
            new_sl = current_price - sl_dist * sl_mult
            new_sl = min(new_sl, current_price * 0.9995)

        if current_tp is not None and current_tp > current_price > entry:
            tp_dist = current_tp - current_price
            new_tp = current_price + tp_dist * tp_mult

    else:
        if current_sl is not None and current_sl > current_price:
            sl_dist = current_sl - current_price
            new_sl = current_price + sl_dist * sl_mult
            new_sl = max(new_sl, current_price * 1.0005)

        if current_tp is not None and current_tp < current_price < entry:
            tp_dist = current_price - current_tp
            new_tp = current_price - tp_dist * tp_mult

    return new_sl, new_tp



