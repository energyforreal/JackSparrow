"""Tests for DecisionContext builder from market_context."""

from __future__ import annotations

from agent.intelligence.cognition.decision_context_builder import (
    build_decision_context_from_market_context,
)


def test_build_from_rule_based_pipeline() -> None:
    mc = {
        "symbol": "BTCUSD",
        "v43_closed_bar_index": 42,
        "features": {"adx_14": 28.0},
        "rule_based_pipeline": {
            "market_state": {
                "symbol": "BTCUSD",
                "bar_index": 42,
                "trend": "bullish",
                "trend_strength": "moderate",
                "momentum": "increasing",
                "volatility": "stable",
                "regime": "trending",
            }
        },
    }
    ctx = build_decision_context_from_market_context(mc, run_cycle=True)
    assert ctx.understanding is not None
    assert ctx.understanding.trend == "bullish"
    assert ctx.meta.bar_index == 42
    assert len(ctx.artifacts) >= 1
