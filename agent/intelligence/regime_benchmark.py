"""Derived regime benchmark labels for analytics cohorts."""

from __future__ import annotations

from typing import Any, Dict

RegimeBenchmark = str

_VALID = frozenset(
    {
        "trending_strong",
        "trending_weak",
        "ranging",
        "volatile",
        "low_volatility",
        "breakout",
        "reversal",
    }
)


def derive_regime_benchmark(market_state: Dict[str, Any]) -> RegimeBenchmark:
    """Map MarketStateSnapshot fields to a first-class regime benchmark label."""
    trend = str(market_state.get("trend") or "neutral").lower()
    strength = str(market_state.get("trend_strength") or "weak").lower()
    volatility = str(market_state.get("volatility") or "stable").lower()
    breakout = str(market_state.get("breakout_status") or "none").lower()
    momentum = str(market_state.get("momentum") or "flat").lower()
    regime = str(market_state.get("regime") or "neutral").lower()

    if breakout in ("confirmed", "forming"):
        return "breakout"
    if volatility == "expanding":
        return "volatile"
    if volatility == "compressing" and regime == "ranging":
        return "low_volatility"
    if trend == "neutral" and momentum == "decreasing":
        return "reversal"
    if regime == "ranging" or trend == "neutral":
        return "ranging"
    if strength == "strong":
        return "trending_strong"
    if trend in ("bullish", "bearish"):
        return "trending_weak"
    return "ranging"


def attach_regime_benchmark(market_state: Dict[str, Any]) -> Dict[str, Any]:
    """Return market_state dict with regime_benchmark attached."""
    out = dict(market_state)
    out["regime_benchmark"] = derive_regime_benchmark(out)
    return out
