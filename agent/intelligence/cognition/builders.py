"""Adapters from existing intelligence types to cognition slices."""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent.intelligence.cognition.types import MarketUnderstanding
from agent.intelligence.market_types import MarketStateSnapshot


def market_state_to_understanding(snapshot: MarketStateSnapshot) -> MarketUnderstanding:
    """Map MarketStateSnapshot to frozen MarketUnderstanding slice."""
    return MarketUnderstanding(
        symbol=snapshot.symbol,
        bar_index=snapshot.bar_index,
        trend=snapshot.trend,
        trend_strength=snapshot.trend_strength,
        trend_age_candles=snapshot.trend_age_candles,
        momentum=snapshot.momentum,
        breakout_status=snapshot.breakout_status,
        retest_status=snapshot.retest_status,
        structure=snapshot.structure,
        liquidity=snapshot.liquidity,
        volatility=snapshot.volatility,
        regime=snapshot.regime,
        confidence=snapshot.confidence,
        direction_bias=snapshot.direction_bias,
        regime_benchmark=snapshot.regime_benchmark,
        mtf=tuple(snapshot.mtf.items()),
    )


def understanding_from_dict(raw: Dict[str, Any]) -> MarketUnderstanding:
    """Build MarketUnderstanding from market_state dict."""
    return MarketUnderstanding.from_dict(raw)


def extract_market_state_dict(market_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve market_state from rule_based_pipeline or top-level keys."""
    mc = market_context or {}
    rb = mc.get("rule_based_pipeline")
    if isinstance(rb, dict):
        ms = rb.get("market_state")
        if isinstance(ms, dict):
            return ms
    ms = mc.get("market_state")
    if isinstance(ms, dict):
        return ms
    return None


def understanding_from_market_context(
    market_context: Dict[str, Any],
) -> Optional[MarketUnderstanding]:
    """Extract understanding slice from legacy market_context."""
    ms = extract_market_state_dict(market_context)
    if ms is None:
        return None
    return understanding_from_dict(ms)


def snapshot_from_market_context(
    market_context: Dict[str, Any],
) -> Optional[MarketStateSnapshot]:
    ms = extract_market_state_dict(market_context)
    if ms is None:
        return None
    return MarketStateSnapshot.from_dict(ms)
