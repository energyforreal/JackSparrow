"""Volatility expansion score (0–1) from structural features."""

from __future__ import annotations

from typing import Any, Dict, Optional


def estimate_vol_expansion(features: Dict[str, Any]) -> float:
    atr_pct = float(features.get("atr_pct", 0.0) or 0.0)
    vol_regime = float(features.get("vol_regime", 1.0) or 1.0)

    raw_ratio = features.get("atr_ratio_14_50")
    atr_ratio: Optional[float]
    if raw_ratio is None:
        atr_ratio = None
    else:
        try:
            atr_ratio = float(raw_ratio)
            if atr_ratio != atr_ratio:
                atr_ratio = None
        except (TypeError, ValueError):
            atr_ratio = None

    if atr_ratio is None and atr_pct > 0:
        atr_ratio = 1.0 + min(2.0, atr_pct * 20.0)
    elif atr_ratio is None:
        atr_ratio = 1.0

    score = min(1.0, max(0.0, (atr_ratio - 1.0) * 2.0)) * min(3.0, max(0.5, vol_regime)) / 3.0
    return float(max(0.0, min(1.0, score)))
