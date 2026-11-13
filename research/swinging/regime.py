"""Regime labels aligned with the agent's structure thresholds.

The label is a training target. It is not a model input.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from research.swinging.contract import (
    HIGH_VOL_ATR_PCT,
    LOW_VOL_ATR_PCT_MAX,
    LOW_VOL_REGIME_MAX,
    RANGE_ADX_MAX,
    RANGE_VOL_REGIME_MAX,
    TREND_ADX_MIN,
    TREND_HURST_MIN,
)


def _number(features: Mapping[str, object], key: str, default: float) -> float:
    raw = features.get(key, default)
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if value != value:
        return default
    return value


def regime_target(features: Mapping[str, object]) -> str:
    """Classify one closed bar the way ``classify_market_structure`` does.

    Args:
        features: Causal feature values. ``atr_pct`` is ATR divided by close.
            Missing keys use the same defaults as the agent helper.

    Returns:
        One of ``trending``, ``ranging``, ``high_volatility``,
        ``low_volatility``, or ``transition``.
    """
    adx = _number(features, "adx_14", 0.0)
    atr_pct = _number(features, "atr_pct", 0.0)
    vol_regime = _number(features, "vol_regime", 1.0)
    hurst = _number(features, "hurst_60", 0.5)
    if atr_pct >= HIGH_VOL_ATR_PCT:
        return "high_volatility"
    if atr_pct > 0.0 and atr_pct < LOW_VOL_ATR_PCT_MAX and vol_regime < LOW_VOL_REGIME_MAX:
        return "low_volatility"
    if adx >= TREND_ADX_MIN and hurst >= TREND_HURST_MIN:
        return "trending"
    if adx < RANGE_ADX_MAX and vol_regime < RANGE_VOL_REGIME_MAX:
        return "ranging"
    return "transition"


def attach_regime_targets(featured: pd.DataFrame) -> pd.DataFrame:
    """Add ``regime_target`` from each row's own feature values.

    Args:
        featured: Feature frame that may include ``atr_14`` and ``close``.

    Returns:
        A copy with ``regime_target``. ``atr_pct`` is filled from ATR and close
        when the caller did not supply it.
    """
    frame = featured.copy()
    if "atr_pct" not in frame.columns and {"atr_14", "close"}.issubset(frame.columns):
        close = pd.to_numeric(frame["close"], errors="coerce").replace(0, pd.NA)
        frame["atr_pct"] = pd.to_numeric(frame["atr_14"], errors="coerce") / close
    labels = [
        regime_target(row.dropna().to_dict())
        for _, row in frame.iterrows()
    ]
    frame["regime_target"] = labels
    return frame
