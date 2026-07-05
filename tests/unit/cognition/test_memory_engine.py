"""Tests for memory decay."""

from __future__ import annotations

import math

from agent.intelligence.cognition.memory_engine import decay_weight, update_memory
from agent.intelligence.cognition.types import BehavioralEvent, MarketMemory, MarketUnderstanding


def test_decay_weight_at_half_life() -> None:
    w = decay_weight(10, half_life=10)
    assert abs(w - math.exp(-1)) < 0.001


def test_memory_accumulates_failed_breakout() -> None:
    prev = MarketMemory(
        symbol="BTCUSD",
        behavioral_events=(BehavioralEvent("failed_breakout", 0, 1.0),),
    )
    mem, _ = update_memory(
        prev,
        symbol="BTCUSD",
        bar_index=20,
        understanding=MarketUnderstanding(symbol="BTCUSD", trend="neutral"),
        narrative_events=[{"event_type": "breakout_failed", "bar_index": 20}],
        features={},
    )
    assert mem.failed_breakout_count >= 1
    assert mem.failed_breakout_weighted >= 0.0
