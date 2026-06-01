"""Structural uncertainty estimate (0–1) for gate compatibility."""

from __future__ import annotations

from typing import Any, Dict


_REGIME_CERTAINTY = {
    "trending": 0.2,
    "ranging": 0.25,
    "neutral": 0.5,
    "crisis": 0.7,
}


def estimate_uncertainty(features: Dict[str, Any], regime: str) -> float:
    adx = float(features.get("adx_14", 0.0) or 0.0)
    hurst = float(features.get("hurst_60", 0.5) or 0.5)
    regime_certainty = _REGIME_CERTAINTY.get(str(regime).lower(), 0.5)

    adx_ambiguity = max(0.0, (25.0 - adx) / 25.0)
    hurst_ambiguity = abs(hurst - 0.5) * 2.0
    ambiguity = adx_ambiguity * hurst_ambiguity
    if 18.0 <= adx < 25.0:
        ambiguity = max(ambiguity, hurst_ambiguity * 0.35)

    return float(min(1.0, regime_certainty + ambiguity * 0.3))
