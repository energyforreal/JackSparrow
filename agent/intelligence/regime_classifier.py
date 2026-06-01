"""Rule-based market regime classification from closed-bar features."""

from __future__ import annotations

from typing import Any, Dict


def _feat(features: Dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = features.get(key)
    if raw is None:
        return default
    try:
        v = float(raw)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def classify_regime(features: Dict[str, Any]) -> str:
    """Return trending | ranging | neutral | crisis from structural features."""
    adx = _feat(features, "adx_14", 0.0)
    atr_pct = _feat(features, "atr_pct", 0.0)
    hurst = _feat(features, "hurst_60", 0.5)
    vol_regime = _feat(features, "vol_regime", 1.0)
    funding = abs(_feat(features, "funding_rate", 0.0))
    if funding <= 0:
        funding = abs(_feat(features, "funding_zscore", 0.0)) * 0.0001

    if funding > 0.002 and atr_pct > 0.015:
        return "crisis"
    if vol_regime > 3.0 and atr_pct > 0.02:
        return "crisis"
    if adx > 25 and hurst > 0.55:
        return "trending"
    if adx < 18 and hurst < 0.48:
        return "ranging"
    return "neutral"
