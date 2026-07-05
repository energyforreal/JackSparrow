"""Tests for expectation engine."""

from __future__ import annotations

from agent.intelligence.cognition.decision_context import CognitionInputs
from agent.intelligence.cognition.expectation_engine import evaluate_expectation
from agent.intelligence.cognition.types import MarketUnderstanding


def test_expectation_produces_horizons() -> None:
    inputs = CognitionInputs(
        understanding=MarketUnderstanding(
            symbol="BTCUSD",
            trend="bullish",
            trend_strength="strong",
            momentum="increasing",
            volatility="compressing",
        ),
        features={
            "adx_14": 32.0,
            "bb_width": 1.2,
            "breakout_score": 0.7,
            "vol_regime": 1.05,
            "ema200_bias": 0.2,
        },
    )
    state, art = evaluate_expectation(inputs)
    assert len(state.horizons) == 4
    assert art.module_id == "expectation"
    assert 0.0 <= state.confidence <= 1.0
    assert state.dominant_expectation in (
        "trend_continuation",
        "breakout",
        "reversal",
        "vol_expansion",
        "neutral",
    )
