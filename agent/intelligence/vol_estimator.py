"""Volatility expansion score (0–1) from structural features."""

from __future__ import annotations

from typing import Any, Dict


def estimate_vol_expansion(features: Dict[str, Any]) -> float:
    atr_pct = float(features.get("atr_pct", 0.0) or 0.0)
    vol_regime = float(features.get("vol_regime", 1.0) or 1.0)
    atr_ratio = float(features.get("atr_ratio_14_50", 1.0) or 1.0)
    if atr_ratio == 1.0 and atr_pct > 0:
        atr_ratio = 1.0 + min(2.0, atr_pct * 20.0)
    score = min(1.0, max(0.0, (atr_ratio - 1.0) * 2.0)) * min(3.0, max(0.5, vol_regime)) / 3.0
    return float(max(0.0, min(1.0, score)))
