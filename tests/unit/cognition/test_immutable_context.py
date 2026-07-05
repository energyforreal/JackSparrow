"""Tests for immutable DecisionContext."""

from __future__ import annotations

from agent.intelligence.cognition.decision_context import DecisionContextBuilder
from agent.intelligence.cognition.types import CognitionMeta, MarketUnderstanding


def test_builder_produces_immutable_context() -> None:
    u = MarketUnderstanding(symbol="BTCUSD", bar_index=10, trend="bullish")
    ctx = (
        DecisionContextBuilder()
        .with_meta(CognitionMeta(symbol="BTCUSD", bar_index=10, cycle_id="c1"))
        .with_understanding(u)
        .build()
    )
    assert ctx.understanding is not None
    assert ctx.understanding.trend == "bullish"
    d = ctx.to_dict()
    restored = type(ctx).from_dict(d)
    assert restored.understanding is not None
    assert restored.understanding.trend == "bullish"


def test_builder_returns_new_instance_on_with() -> None:
    b1 = DecisionContextBuilder()
    b2 = b1.with_understanding(MarketUnderstanding(symbol="X"))
    assert b1 is not b2
    assert b1.build().understanding is None
    assert b2.build().understanding is not None
